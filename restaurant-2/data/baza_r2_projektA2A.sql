CREATE TABLE konto (
    id INTEGER PRIMARY KEY,
    balans REAL NOT NULL
);

CREATE TABLE magazyn (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa_produktu TEXT UNIQUE NOT NULL,
    ilosc REAL NOT NULL,
    jednostka TEXT NOT NULL
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

INSERT INTO konto (id, balans) VALUES (1, 15000.00);

insert into magazyn (nazwa_produktu, ilosc, jednostka)
VALUES
    ('Flour', 20, 'kg'),
    ('Passata', 10, 'kg'),
    ('Mozzarella', 15, 'kg'),
    ('Parmigiano reggiano', 5, 'kg'),
    ('Salami', 7, 'kg'),
    ('Lamb`s lettuce', 500, 'kg'),
    ('Prosciutto crudo', 3, 'kg'),
    ('Buffala', 2.4, 'kg');

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





