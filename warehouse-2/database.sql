
CREATE DATABASE IF NOT EXISTS warehouse2 ;

USE warehouse2;
DROP TABLE IF EXISTS warehouse;
CREATE TABLE IF NOT EXISTS warehouse2 (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) UNIQUE NOT NULL,
    quantity INT NOT NULL,
    price DOUBLE NOT NULL,
    unit VARCHAR(20) NOT NULL
);

INSERT INTO warehouse2
    (name, quantity, price, unit)
VALUES
    ('Flour', 50, 2.00, 'kg'),
    ('Passata', 75, 1.00, 'kg'),
    ('Mozzarella', 60, 1.50, 'kg'),
    ('Parmigiano reggiano', 80, 2.50, 'kg'),
    ('Burrata', 30, 1.50, 'kg'),
    ('Buffala', 200, 0.20, 'kg'),
    ('Prosciutto cotto', 100, 4.50, 'kg'),
    ('Prosciutto crudo', 150, 0.50, 'kg'),
    ('Arugula', 100, 0.30, 'kg'),
    ('Lamb''s lettuce', 80, 0.20, 'kg'),
    ('Salami', 120, 0.40, 'kg');

CREATE TABLE IF NOT EXISTS wallet_warehouse2 (
    id INT PRIMARY KEY AUTO_INCREMENT,
    sender_id VARCHAR(20) NOT NULL,
    receiver_id VARCHAR(20) NOT NULL,
    type ENUM('INCOME', 'EXPENSE') NOT NULL,
    ballance DOUBLE NOT NULL
);


INSERT INTO wallet_warehouse2 (sender_id, receiver_id, type, ballance) 
VALUES ('SYSTEM', 'H2', 'INCOME', 10000.00);