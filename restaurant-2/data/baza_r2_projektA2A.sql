CREATE TABLE konto (
    id INTEGER PRIMARY KEY,
    balans REAL NOT NULL
);

CREATE TABLE magazyn (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa_produktu TEXT UNIQUE NOT NULL,
    ilosc REAL NOT NULL,
    jednostka TEXT NOT NULL,
    prog_bezpieczenstwa REAL DEFAULT 5.0
);

CREATE TABLE historia_transakcji (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    typ_akcji TEXT,
    od_kogo TEXT,
    produkt TEXT,
    ilosc REAL,
    koszt REAL,
    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

create table przepisy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa_dania TEXT UNIQUE NOT NULL
);

CREATE TABLE skladniki_przepisow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_przepisu INTEGER NOT NULL,
    nazwa_produktu TEXT NOT NULL,
    ilosc_wymagana REAL NOT NULL,
    FOREIGN KEY (id_przepisu) REFERENCES przepisy(id)
);

CREATE TABLE zadania_oczekujace (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa_dania TEXT NOT NULL,
    ilosc_porcji INTEGER NOT NULL,
    status TEXT DEFAULT 'OCZEKUJE'
);

INSERT INTO konto (id, balans) VALUES (1, 15000.00);

INSERT INTO magazyn (nazwa_produktu, ilosc, jednostka, prog_bezpieczenstwa)
VALUES
    ('Flour', 20, 'kg', 10.0),
    ('Passata', 10, 'kg', 5.0),
    ('Mozzarella', 15, 'kg', 5.0),
    ('Parmigiano reggiano', 5, 'kg', 2.0),
    ('Salami', 7, 'kg', 3.0),
    ('Lamb`s lettuce', 500, 'kg', 10.0),
    ('Prosciutto crudo', 3, 'kg', 3.0),
    ('Buffala', 2.4, 'kg', 5.0);

INSERT INTO przepisy (id, nazwa_dania) VALUES
    (1, 'Pizza z salami'),
    (2, 'Sałatka z burrata'),
    (3, 'Roladki z prosciutto'),
    (4, 'Calzone z mozzarellą'),
    (5, 'Sałatka z salami');

INSERT INTO skladniki_przepisow (id_przepisu, nazwa_produktu, ilosc_wymagana)
VALUES
    (1, 'Flour', 0.25),
    (1, 'Passata', 0.15),
    (1, 'Mozzarella', 0.125),
    (1, 'Salami', 0.08),
    (1, 'Parmigiano reggiano', 0.03),
    (2, 'Arugula', 0.1),
    (2, 'Burrata', 0.15),
    (2, 'Prosciutto crudo', 0.08),
    (3, 'Prosciutto cotto', 0.1),
    (3, 'Buffala', 0.125),
    (3, 'Lamb`s lettuce', 0.05),
    (4, 'Flour', 0.2),
    (4, 'Passata', 0.1),
    (4, 'Mozzarella', 0.125),
    (4, 'Prosciutto cotto', 0.08),
    (5, 'Lamb`s lettuce', 0.1),
    (5, 'Arugula', 0.05),
    (5, 'Salami', 0.07),
    (5, 'Parmigiano reggiano', 0.04);





