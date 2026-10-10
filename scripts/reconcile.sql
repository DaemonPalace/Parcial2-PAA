-- NFR-04 reconciliation across every service schema (run as the DB superuser):
--   docker compose exec -T postgres psql -U supabase_admin -d postgres -f - < scripts/reconcile.sql
-- Every count must be 0.
with res as (
    select order_id, status from flights.flight_reservations
    union all select order_id, status from hotels.hotel_reservations
    union all select order_id, status from cars.car_reservations
)
select 'orders not in a terminal state' as check, count(*) as violations
    from orders.orders where status not in ('CONFIRMED', 'CANCELLED', 'REJECTED')
union all
select 'orphan reservations (RESERVED for an order that is not CONFIRMED)', count(*)
    from res join orders.orders o on o.id = res.order_id where res.status = 'RESERVED' and o.status <> 'CONFIRMED'
union all
select 'retained charges (CHARGED for an order that is not CONFIRMED)', count(*)
    from orders.payments p join orders.orders o on o.id = p.order_id where p.status = 'CHARGED' and o.status <> 'CONFIRMED'
union all
select 'CONFIRMED orders missing a reservation or the charge', count(*)
    from orders.orders o where o.status = 'CONFIRMED' and (
        (select count(*) from res where res.order_id = o.id and res.status = 'RESERVED') <> 3
        or not exists (select 1 from orders.payments p where p.order_id = o.id and p.status = 'CHARGED'))
union all
select 'held units (RESERVED) with no order at all', count(*)
    from res where res.status = 'RESERVED' and not exists (select 1 from orders.orders o where o.id = res.order_id);
