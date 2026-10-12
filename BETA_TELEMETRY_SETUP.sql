-- Additive Beta integration. Reuses existing token hashes; does not alter QQQ reports.
-- Apply once in the SAME Supabase project as Victor Terminal.
begin;
do $$ begin
 if not exists (select 1 from vt_private.access where id=1) then
  raise exception 'Set up existing Victor telemetry first';
 end if;
end $$;
create table if not exists vt_private.beta_latest (
 id integer primary key check (id=1), observed_at timestamptz not null,
 received_at timestamptz not null default clock_timestamp(), snapshot jsonb not null
);
alter table vt_private.beta_latest enable row level security;
revoke all on vt_private.beta_latest from public, anon, authenticated;

create or replace function public.vt_beta_read(p_token text) returns jsonb
language plpgsql security definer set search_path = '' as $$
begin
 if p_token is null or not exists (
  select 1 from vt_private.access where id=1
   and read_hash=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_token,'UTF8')),'hex')
 ) then raise exception 'Access denied' using errcode='42501'; end if;
 return (select pg_catalog.jsonb_build_object('received_at',received_at,'snapshot',snapshot)
         from vt_private.beta_latest where id=1);
end; $$;

create or replace function public.vt_beta_write(p_token text,p_snapshot jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare observed timestamptz;
begin
 if p_token is null or not exists (
  select 1 from vt_private.access where id=1
   and write_hash=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_token,'UTF8')),'hex')
 ) then raise exception 'Access denied' using errcode='42501'; end if;
 if p_snapshot is null or pg_catalog.jsonb_typeof(p_snapshot) is distinct from 'object'
  or (p_snapshot->'schema') is distinct from '1'::jsonb
  or (p_snapshot->'paper') is distinct from 'true'::jsonb
  or pg_catalog.jsonb_typeof(p_snapshot->'positions') is distinct from 'array'
  or pg_catalog.jsonb_typeof(p_snapshot->'dossiers') is distinct from 'array'
  or pg_catalog.octet_length(p_snapshot::text)>8500000
 then raise exception 'Invalid report' using errcode='22023'; end if;
 observed := (p_snapshot->>'observed_at')::timestamptz;
 if observed is null or observed > pg_catalog.clock_timestamp()+interval '60 seconds'
    or observed < pg_catalog.clock_timestamp()-interval '5 minutes'
 then raise exception 'Check sender clock' using errcode='22023'; end if;
 insert into vt_private.beta_latest as current_row(id,observed_at,received_at,snapshot)
 values(1,observed,pg_catalog.clock_timestamp(),p_snapshot)
 on conflict(id) do update set observed_at=excluded.observed_at,
 received_at=excluded.received_at,snapshot=excluded.snapshot
 where excluded.observed_at>current_row.observed_at;
 return pg_catalog.jsonb_build_object('ok',true);
end; $$;
revoke all on function public.vt_beta_read(text) from public, anon, authenticated;
revoke all on function public.vt_beta_write(text,jsonb) from public, anon, authenticated;
grant execute on function public.vt_beta_read(text) to anon;
grant execute on function public.vt_beta_write(text,jsonb) to anon;
notify pgrst, 'reload schema';
commit;

