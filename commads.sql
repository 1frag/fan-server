create table app_user (
    id serial primary key,
    login varchar(64) unique not null,
    pwd varchar(64) not null,
    email varchar(128) not null unique,
    custom_id varchar(128) not null,
    auth_code varchar(32) not null,
    confirmed boolean default false,
    token varchar(128) default null
);

create table app_taken_place (
    user_id int references app_user(id) on delete cascade not null,
    game int not null,
    sector int not null,
    trow int not null,
    place int not null,
    constraint taken_place_unique unique (game, sector, trow, place)
);

create function get_user_id_by_token(
    cur_token varchar(128)
) returns int as $$
declare
    target int;
begin
    select id from app_user u
    where u.token = cur_token
    into target;
    return target;
end;
$$ language plpgsql;
