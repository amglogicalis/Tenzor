create table if not exists public.model_lifecycle_state (
    id text primary key,
    endpoint_resource text not null,
    model_resource text not null,
    status text not null check (status in ('sleep', 'waking', 'active', 'sleeping', 'error')),
    operation_name text,
    operation_kind text check (operation_kind in ('deploy', 'undeploy') or operation_kind is null),
    operation_started_at timestamptz,
    message text,
    updated_at timestamptz not null default now()
);

create index if not exists model_lifecycle_state_status_idx
    on public.model_lifecycle_state (status);
