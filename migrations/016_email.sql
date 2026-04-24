-- Gmail OAuth tokens per user
create table if not exists user_gmail_tokens (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    gmail_address text not null,
    access_token text not null,
    refresh_token text not null,
    token_expiry timestamptz,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique (user_id)
);

-- Email send log
create table if not exists email_logs (
    id uuid primary key default gen_random_uuid(),
    contact_id uuid not null references contacts(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    gmail_address text not null,
    recipient_email text not null,
    subject text not null,
    body text not null,
    outcome_context text,
    sent_at timestamptz default now()
);

create index if not exists idx_email_logs_contact on email_logs(contact_id);

-- Email templates on settings
alter table settings
    add column if not exists email_template_didnt_pick_up text not null default '',
    add column if not exists email_template_interested text not null default '',
    add column if not exists email_subject_didnt_pick_up text not null default 'Following up',
    add column if not exists email_subject_interested text not null default 'Great chatting with you';
