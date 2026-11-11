-- Gangway: port days shared by crew.
-- Run this once in your Supabase project: Dashboard -> SQL Editor -> New query -> paste -> Run.
-- Safe to run again: it replaces the functions and view and keeps the data.
--
-- What is stored: ship name, date, port id, optional sailing time, and a random id the app makes
-- for each phone (so one phone counts once per ship and day). No names, emails or locations.
--
-- Access for the app (the public "anon" key):
--   * cannot read or change the table directly;
--   * can add or replace its own day with add_crew_day(), and remove it with remove_crew_day();
--   * can read crew_consensus: for each ship, day and port, how many phones reported it.

create table if not exists public.crew_days (
  id         bigint generated always as identity primary key,
  ship       text not null check (char_length(ship) between 2 and 60),
  ship_key   text generated always as (regexp_replace(lower(ship), '[^a-z0-9]', '', 'g')) stored,
  day        date not null,
  port       text not null check (port ~ '^[a-z0-9]{2,8}$'),
  sail_out   time,
  device     uuid not null,
  created_at timestamptz not null default now(),
  unique (ship_key, day, device)
);
create index if not exists crew_days_day on public.crew_days (day);
create index if not exists crew_days_device on public.crew_days (device, created_at);

alter table public.crew_days enable row level security;   -- no policies: no direct access for anon
revoke all on public.crew_days from anon, authenticated;

-- Add (or replace) this phone's port for a ship on a day.
create or replace function public.add_crew_day(p_device uuid, p_ship text, p_day date, p_port text, p_out time default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  if p_day < current_date - 2 or p_day > current_date + 800 then raise exception 'date out of range'; end if;
  -- Light abuse limits per phone: 120 days an hour, 1500 upcoming days in total.
  if (select count(*) from crew_days where device = p_device and created_at > now() - interval '1 hour') >= 120
     or (select count(*) from crew_days where device = p_device and day >= current_date) >= 1500 then
    raise exception 'too many entries';
  end if;
  insert into crew_days (ship, day, port, sail_out, device)
  values (trim(p_ship), p_day, lower(p_port), p_out, p_device)
  on conflict (ship_key, day, device)
  do update set port = excluded.port, sail_out = excluded.sail_out, ship = excluded.ship, created_at = now();
end $$;

-- Remove this phone's entry for a ship on a day.
create or replace function public.remove_crew_day(p_device uuid, p_ship text, p_day date)
returns void language sql security definer set search_path = public as $$
  delete from crew_days
  where device = p_device and day = p_day and ship_key = regexp_replace(lower(p_ship), '[^a-z0-9]', '', 'g');
$$;

revoke all on function public.add_crew_day(uuid, text, date, text, time) from public;
revoke all on function public.remove_crew_day(uuid, text, date) from public;
grant execute on function public.add_crew_day(uuid, text, date, text, time) to anon, authenticated;
grant execute on function public.remove_crew_day(uuid, text, date) to anon, authenticated;

-- What the app reads: upcoming crew days, counted per ship, day and port. Device ids are never exposed.
create or replace view public.crew_consensus as
select ship_key,
       max(ship)                                                           as ship,
       day,
       port,
       count(*)::int                                                       as n,
       mode() within group (order by sail_out) filter (where sail_out is not null) as sail_out
from public.crew_days
where day >= current_date - 1
group by ship_key, day, port;

revoke all on public.crew_consensus from anon, authenticated;
grant select on public.crew_consensus to anon, authenticated;
