-- WanderSync schema (docs/design.md §4). Runs once, on an empty data volume, as
-- supabase_admin via the supabase/postgres image's migrate.sh (mounted into
-- /docker-entrypoint-initdb.d/migrations/). Role passwords come from the
-- container environment (.env), never from this file.
\set ON_ERROR_STOP on

\getenv flights_pw FLIGHTS_DB_PASSWORD
\getenv hotels_pw HOTELS_DB_PASSWORD
\getenv cars_pw CARS_DB_PASSWORD
\getenv orders_pw ORDERS_DB_PASSWORD
\getenv gateway_pw GATEWAY_DB_PASSWORD
\getenv ingestion_pw INGESTION_DB_PASSWORD

create extension if not exists pg_graphql;

-- ─────────── Roles: one login per owner (NFR-03) ───────────
create role flights_svc   login password :'flights_pw';
create role hotels_svc    login password :'hotels_pw';
create role cars_svc      login password :'cars_pw';
create role orders_svc    login password :'orders_pw';
create role gateway_svc   login password :'gateway_pw';
create role ingestion_svc login password :'ingestion_pw';

create schema flights  authorization flights_svc;
create schema hotels   authorization hotels_svc;
create schema cars     authorization cars_svc;
create schema orders   authorization orders_svc;
create schema accounts authorization gateway_svc;
create schema catalog;  -- read model, owned by the migration superuser

-- Each role only resolves its own schema by default.
alter role flights_svc   set search_path = flights;
alter role hotels_svc    set search_path = hotels;
alter role cars_svc      set search_path = cars;
alter role orders_svc    set search_path = orders;
-- catalog only: pg_graphql exposes what's on the search_path, and accounts
-- (password hashes) must never become reachable through GraphQL.
alter role gateway_svc   set search_path = catalog;

-- ─────────── flights ───────────
set role flights_svc;

create table flights.flight_offers (
    id               bigint generated always as identity primary key,
    source           text        not null,
    airline          text        not null,
    origin           char(3)     not null,
    destination      char(3)     not null,
    depart_at        timestamptz not null,
    arrive_at        timestamptz,
    duration_minutes int,
    stops            int,
    price_cop        int         not null check (price_cop > 0),
    seats_available  int         not null default 5 check (seats_available >= 0),
    scraped_at       timestamptz not null default now(),
    unique (source, airline, origin, destination, depart_at),
    check (origin <> destination)
);
create index on flights.flight_offers (origin, destination, depart_at);

-- order_id unique = idempotency record. offer_id null = tombstone written by a
-- cancel that arrived before (or instead of) its reserve (design §3.6).
create table flights.flight_reservations (
    id         bigint generated always as identity primary key,
    order_id   uuid        not null unique,
    offer_id   bigint      references flights.flight_offers (id),
    status     text        not null check (status in ('RESERVED', 'CANCELLED')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

reset role;

-- ─────────── hotels ───────────
set role hotels_svc;

create table hotels.hotel_offers (
    id              bigint generated always as identity primary key,
    source          text        not null,
    name            text        not null,
    city            char(3)     not null,
    check_in        date        not null,
    check_out       date        not null,
    rating          numeric(3, 1),
    price_total_cop int         not null check (price_total_cop > 0),
    url             text,
    rooms_available int         not null default 5 check (rooms_available >= 0),
    scraped_at      timestamptz not null default now(),
    unique (source, name, city, check_in, check_out),
    check (check_out > check_in)
);
create index on hotels.hotel_offers (city, check_in, check_out);

create table hotels.hotel_reservations (
    id         bigint generated always as identity primary key,
    order_id   uuid        not null unique,
    offer_id   bigint      references hotels.hotel_offers (id),
    status     text        not null check (status in ('RESERVED', 'CANCELLED')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

reset role;

-- ─────────── cars ───────────
set role cars_svc;

create table cars.car_offers (
    id              bigint generated always as identity primary key,
    source          text        not null,
    vendor          text        not null,
    model           text        not null,
    category        text,
    city            char(3)     not null,
    pickup_date     date        not null,
    dropoff_date    date        not null,
    price_total_cop int         not null check (price_total_cop > 0),
    units_available int         not null default 5 check (units_available >= 0),
    scraped_at      timestamptz not null default now(),
    unique (source, vendor, model, city, pickup_date, dropoff_date),
    check (dropoff_date > pickup_date)
);
create index on cars.car_offers (city, pickup_date, dropoff_date);

create table cars.car_reservations (
    id         bigint generated always as identity primary key,
    order_id   uuid        not null unique,
    offer_id   bigint      references cars.car_offers (id),
    status     text        not null check (status in ('RESERVED', 'CANCELLED')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

reset role;

-- ─────────── orders (orders-billing-svc) ───────────
set role orders_svc;

create table orders.orders (
    id              uuid        primary key default gen_random_uuid(),
    idempotency_key uuid        not null unique,
    user_id         uuid        not null,
    flight_offer_id bigint      not null,
    hotel_offer_id  bigint      not null,
    car_offer_id    bigint      not null,
    total_cop       int         not null check (total_cop > 0),
    status          text        not null default 'PENDING' check (status in
                        ('PENDING', 'RUNNING', 'CONFIRMED', 'COMPENSATING', 'CANCELLED', 'REJECTED')),
    failure_reason  text,
    chaos           jsonb,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index on orders.orders (user_id, created_at desc);
-- crash recovery scans only unfinished orders (design §3.9)
create index on orders.orders (status) where status in ('PENDING', 'RUNNING', 'COMPENSATING');

create table orders.payments (
    order_id    uuid        primary key references orders.orders (id),
    amount_cop  int         not null check (amount_cop > 0),
    status      text        not null check (status in ('CHARGED', 'REFUNDED')),
    charged_at  timestamptz not null default now(),
    refunded_at timestamptz
);

create table orders.saga_steps (
    id         bigint generated always as identity primary key,
    order_id   uuid        not null references orders.orders (id),
    name       text        not null check (name in ('PAYMENT', 'FLIGHT', 'HOTEL', 'CAR')),
    action     text        not null check (action in ('FORWARD', 'COMPENSATE')),
    status     text        not null check (status in ('RUNNING', 'SUCCEEDED', 'FAILED')),
    error      text,
    started_at timestamptz not null default now(),
    ended_at   timestamptz
);
create index on orders.saga_steps (order_id, id);

reset role;

-- ─────────── accounts (gateway) ───────────
set role gateway_svc;

create table accounts.users (
    id            uuid        primary key default gen_random_uuid(),
    email         text        not null check (email = lower(email)),
    password_hash text        not null check (password_hash like '$argon2id$%'),
    role          text        not null default 'TRAVELER' check (role in ('TRAVELER', 'ADMIN')),
    created_at    timestamptz not null default now(),
    unique (email)
);

-- token_hash = sha256(cookie token): a DB leak doesn't leak live sessions.
-- user_id null = anonymous session (pre-login, rotated on login).
create table accounts.sessions (
    token_hash text        primary key,
    user_id    uuid        references accounts.users (id) on delete cascade,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null
);
create index on accounts.sessions (expires_at);

reset role;

-- ─────────── catalog: read model for the gateway via pg_graphql ───────────
-- Views run with their owner's (superuser's) rights, so gateway_svc can read
-- offers without any grant on the flights/hotels/cars schemas themselves.
create view catalog.flight_offers as
    select id, source, airline, origin, destination, depart_at, arrive_at,
           duration_minutes, stops, price_cop, seats_available, scraped_at
    from flights.flight_offers;

create view catalog.hotel_offers as
    select id, source, name, city, check_in, check_out, rating, price_total_cop,
           url, rooms_available, scraped_at
    from hotels.hotel_offers;

create view catalog.car_offers as
    select id, source, vendor, model, category, city, pickup_date, dropoff_date,
           price_total_cop, units_available, scraped_at
    from cars.car_offers;

comment on schema catalog is e'@graphql({"inflect_names": true})';
comment on view catalog.flight_offers is e'@graphql({"primary_key_columns": ["id"]})';
comment on view catalog.hotel_offers  is e'@graphql({"primary_key_columns": ["id"]})';
comment on view catalog.car_offers    is e'@graphql({"primary_key_columns": ["id"]})';

grant usage on schema catalog to gateway_svc;
grant select on all tables in schema catalog to gateway_svc;
grant usage on schema graphql to gateway_svc;
grant execute on all functions in schema graphql to gateway_svc;

-- ─────────── ingestion: upsert offers only, never inventory ───────────
-- Inventory columns are set on INSERT (column default) and are not in the
-- UPDATE grant, so a re-scrape can't overwrite seats/rooms/units that live
-- reservations depend on (ADR-07).
grant usage on schema flights, hotels, cars to ingestion_svc;
grant select, insert on flights.flight_offers, hotels.hotel_offers, cars.car_offers to ingestion_svc;
grant update (price_cop, arrive_at, duration_minutes, stops, scraped_at) on flights.flight_offers to ingestion_svc;
grant update (price_total_cop, rating, url, scraped_at) on hotels.hotel_offers to ingestion_svc;
grant update (price_total_cop, category, scraped_at) on cars.car_offers to ingestion_svc;
