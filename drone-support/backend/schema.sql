-- Схема PostgreSQL / Supabase для промислового розгортання.
-- Поля відповідають об'єктам у assets/store.js, тому перенесення даних з
-- резервної копії JSON — пряме відображення колонок.

create table users (
  id          text primary key,
  name        text not null,
  role        text not null check (role in ('consultant', 'head')),
  pin_hash    text not null,                 -- у промисловій версії: хеш PIN або SSO
  rate        numeric(10,2) not null default 0,  -- ставка, грн/год
  active      boolean not null default true,
  hired_at    date not null,
  left_at     date
);

create table shifts (
  id          text primary key,
  uid         text not null references users(id),
  start_at    timestamptz not null,
  end_at      timestamptz,                    -- null = чергування триває
  fatigue     smallint check (fatigue between 1 and 5),
  handover    text not null default ''
);
create index on shifts (uid, start_at);

create table requests (
  id          text primary key,
  uid         text not null references users(id),
  sid         text not null references shifts(id),
  ts          timestamptz not null,
  ch          text not null check (ch in ('sig', 'tg', 'wa', 'tel')),
  type        text not null check (type in ('fw', 'vid', 'rc', 'pwr', 'dmg', 'pay', 'edu', 'log')),
  pr          text not null check (pr in ('crit', 'high', 'norm')),
  prod        text not null,
  frt         integer not null check (frt >= 0),     -- перша відповідь, с
  dur         integer not null check (dur >= 1),     -- обробка, хв
  out         text not null check (out in ('ok', 'esc', 'rma', 'wait')),
  back        boolean not null default false,        -- техніку повернуто в стрій
  rate        smallint check (rate between 1 and 5), -- оцінка оператора
  note        text not null
);
create index on requests (ts);
create index on requests (uid, ts);

create table proposals (
  id          text primary key,
  uid         text not null references users(id),
  ts          timestamptz not null,
  section     text not null,                  -- номер пункту регламенту або 'new'
  text        text not null,
  reason      text not null default '',
  status      text not null default 'new' check (status in ('new', 'review', 'accepted', 'rejected')),
  comment     text not null default '',
  decided_at  timestamptz
);

create table settings (
  id          text primary key default 'main',
  data        jsonb not null
);

-- Рекомендовані правила доступу (Row Level Security у Supabase):
--   консультант бачить і змінює лише свої shifts/requests, читає всі proposals свого авторства;
--   керівник читає все, змінює users, settings, proposals.status/comment.
