CREATE TABLE IF NOT EXISTS venues (
  id SERIAL PRIMARY KEY,
  name VARCHAR UNIQUE,
  edfringe_number INTEGER,
  address VARCHAR,
  latlong POINT
);

CREATE TABLE IF NOT EXISTS shows (
  id SERIAL PRIMARY KEY,
  edfringe_url VARCHAR UNIQUE,
  title VARCHAR,
  category VARCHAR,
  venue_id INTEGER REFERENCES venues(id),
  duration INTERVAL
);

CREATE TABLE IF NOT EXISTS performances (
  id SERIAL PRIMARY KEY,
  show_id INTEGER REFERENCES shows(id),
  datetime_utc TIMESTAMP WITH TIME ZONE,
  UNIQUE(show_id, datetime_utc)
);

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email VARCHAR UNIQUE,
  password_hash VARCHAR,
  start_datetime_utc TIMESTAMP WITH TIME ZONE,
  end_datetime_utc TIMESTAMP WITH TIME ZONE,
  confirm_email_token VARCHAR,
  import_token VARCHAR UNIQUE
);

CREATE TABLE IF NOT EXISTS interests (
  id SERIAL PRIMARY KEY,
  show_id INTEGER REFERENCES shows(id),
  user_id INTEGER REFERENCES users(id),
  interest VARCHAR, -- Booked, Must, Like
  UNIQUE(show_id, user_id)
);

CREATE TABLE IF NOT EXISTS bookings (
  id SERIAL PRIMARY KEY,
  show_id INTEGER REFERENCES shows(id),
  performance_id INTEGER REFERENCES performances(id),
  user_id INTEGER REFERENCES users(id),
  UNIQUE(performance_id, user_id)
);

CREATE TABLE IF NOT EXISTS shares (
  id SERIAL PRIMARY KEY,
  shared_by INTEGER REFERENCES users(id),
  shared_with_email VARCHAR,
  UNIQUE(shared_by, shared_with_email)
);
