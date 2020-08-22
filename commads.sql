create table app_user (
    login varchar(64) not null,
    pwd varchar(64) not null,
    email varchar(128) not null,
    custom_id varchar(128) not null,
    auth_code varchar(32) not null,
    confirmed boolean default false
);

