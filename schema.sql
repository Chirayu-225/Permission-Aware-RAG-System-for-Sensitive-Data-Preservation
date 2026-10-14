-- ============================================================
-- Permission-Aware RAG: Supabase schema
-- Run this in Supabase Dashboard -> SQL Editor -> New query
-- Safe to re-run: policies are dropped and recreated, functions are replaced.
-- ============================================================

-- 1. Enable pgvector
create extension if not exists vector;

-- 2. Profiles table: maps each auth user to a department
-- (Supabase auto-creates auth.users; we extend it with our own table)
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  department text not null,   -- 'hr' | 'finance' | 'engineering' | 'unassigned' (default, no access)
  role text not null default 'employee'  -- 'employee' | 'manager'
);

alter table profiles enable row level security;

-- users can read their own profile row (needed so match_chunks can look it up)
drop policy if exists "read own profile" on profiles;
create policy "read own profile"
on profiles for select
using (auth.uid() = id);

-- 3. Chunks table: the "documents" our RAG retrieves from
create table if not exists chunks (
  id bigserial primary key,
  doc_title text not null,
  content text not null,
  embedding vector(384),         -- all-MiniLM-L6-v2 output size
  department text not null,      -- which dept this content belongs to
  classification text not null   -- 'public' | 'internal' | 'restricted'
);

alter table chunks enable row level security;

-- THE CORE SECURITY POLICY
-- A row is visible if it's public, OR if it belongs to the caller's own department.
-- 'restricted' rows outside your department are never visible, full stop.
drop policy if exists "dept-scoped read" on chunks;
create policy "dept-scoped read"
on chunks for select
using (
  classification = 'public'
  or department = (select department from profiles where id = auth.uid())
);

-- 4. Vector similarity search function.
-- IMPORTANT: no "security definer" here -> it runs as SECURITY INVOKER by default,
-- meaning it runs with the CALLING USER's permissions, so RLS above still applies
-- inside this function. This one line is the entire security boundary.
create or replace function match_chunks(
  query_embedding vector(384),
  match_count int default 5
)
returns table (
  id bigint,
  doc_title text,
  content text,
  department text,
  classification text,
  similarity float
)
language sql
stable
as $$
  select
    id,
    doc_title,
    content,
    department,
    classification,
    1 - (embedding <=> query_embedding) as similarity
  from chunks
  order by embedding <=> query_embedding
  limit match_count;
$$;

-- 5. Auto-create a profile row when a new auth user signs up.
-- SECURITY FIX: new users start in 'unassigned', a value no document ever
-- uses, so a brand-new account can read public content only. Previously the
-- placeholder was 'engineering', which meant ANYONE able to sign up could read
-- engineering's restricted documents. Departments are granted deliberately,
-- by an admin (create_users.py), never by default. Also turn off public
-- sign-ups in the Supabase Auth settings (see README).
create or replace function handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, department)
  values (new.id, new.email, 'unassigned');
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();
