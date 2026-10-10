-- Baseline offers (source = 'seed') for the next 30 days, so search and booking
-- work before — or without — a successful scrape of the real sites (D-006).
-- Prices are deterministic (hashtext) so evidence is reproducible.
-- Stays and rentals: 1–7 nights, matching the search form's limits.
\set ON_ERROR_STOP on

create temporary table seed_cities (code char(3), name text, hub_cost int);
insert into seed_cities values
    ('BOG', 'Bogotá',       0),
    ('MDE', 'Medellín',     40000),
    ('CLO', 'Cali',         50000),
    ('CTG', 'Cartagena',    120000),
    ('SMR', 'Santa Marta',  110000),
    ('BAQ', 'Barranquilla', 100000);

-- seed helper: deterministic integer in [0, n)
create function pg_temp.h(t text, n int) returns int
    language sql immutable as $$ select abs(hashtext(t)) % n $$;

insert into flights.flight_offers
    (source, airline, origin, destination, depart_at, arrive_at, duration_minutes, stops, price_cop)
select 'seed', a.airline, o.code, d.code,
       (day::date + a.hour) at time zone 'America/Bogota',
       (day::date + a.hour + make_interval(mins => 60 + pg_temp.h(o.code || d.code, 50))) at time zone 'America/Bogota',
       60 + pg_temp.h(o.code || d.code, 50),
       0,
       (150000 + o.hub_cost + d.hub_cost + pg_temp.h(a.airline || o.code || d.code || day::text, 250) * 1000)
from seed_cities o
cross join seed_cities d
cross join generate_series(current_date + 1, current_date + 30, interval '1 day') as day
cross join (values ('Avianca', interval '6 hours'), ('LATAM', interval '11 hours'), ('Wingo', interval '17 hours 30 minutes')) as a(airline, hour)
where o.code <> d.code;

insert into hotels.hotel_offers (source, name, city, check_in, check_out, rating, price_total_cop, url)
select 'seed', h.prefix || ' ' || c.name, c.code, day::date, day::date + nights,
       round((7 + pg_temp.h(h.prefix || c.code, 30) / 10.0)::numeric, 1),
       nights * (140000 + pg_temp.h(h.prefix || c.code || day::text, 400) * 1000),
       null
from seed_cities c
cross join generate_series(current_date + 1, current_date + 30, interval '1 day') as day
cross join generate_series(1, 7) as nights
cross join (values ('Hotel Plaza'), ('Casa Boutique'), ('Hostal del Parque')) as h(prefix);

insert into cars.car_offers (source, vendor, model, category, city, pickup_date, dropoff_date, price_total_cop)
select 'seed', v.vendor, v.model, v.category, c.code, day::date, day::date + days,
       days * (v.daily + pg_temp.h(v.vendor || c.code || day::text, 60) * 1000)
from seed_cities c
cross join generate_series(current_date + 1, current_date + 30, interval '1 day') as day
cross join generate_series(1, 7) as days
cross join (values ('Localiza', 'Kia Picanto', 'Económico', 85000),
                   ('Hertz', 'Renault Duster', 'SUV', 160000),
                   ('Budget', 'Chevrolet Onix', 'Compacto', 110000)) as v(vendor, model, category, daily);
