-- Storage bucket for worker-captured captcha screenshots
-- (services/captcha.py uploads here; auth/hh_auth.py during OAuth captcha handoff).
insert into storage.buckets (id, name, public)
values ('captcha-screenshots', 'captcha-screenshots', false)
on conflict (id) do nothing;
