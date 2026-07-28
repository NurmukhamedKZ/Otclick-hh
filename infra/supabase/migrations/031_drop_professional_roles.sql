-- Drop the professional_role search filter. It was seeded from the resume back
-- when a bare filter matched every vacancy; `text` (also seeded from the resume)
-- plus `search_field=name` from migration 030 do that job, and the role AND-ed on
-- top mostly dropped correct vacancies that the employer had tagged loosely.
-- resumes.professional_roles existed only to seed it.

alter table filters drop column if exists professional_role;
alter table resumes drop column if exists professional_roles;
