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

