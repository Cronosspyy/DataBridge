CREATE TABLE customers (
    customer_id BIGINT PRIMARY KEY,
    name TEXT,
    email TEXT,
    gender TEXT,
    signup_date DATE,
    country TEXT
);

CREATE TABLE products (
    product_id BIGINT PRIMARY KEY,
    product_name TEXT,
    category TEXT,
    price NUMERIC(10,2),
    stock_quantity INTEGER,
    brand TEXT
);

CREATE TABLE orders (
    order_id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    order_date DATE,
    total_amount NUMERIC(12,2),
    payment_method TEXT,
    shipping_country TEXT,

    CONSTRAINT fk_orders_customer
        FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
    order_item_id BIGINT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INTEGER,
    unit_price NUMERIC(10,2),

    CONSTRAINT fk_order_items_order
        FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    CONSTRAINT fk_order_items_product
        FOREIGN KEY (product_id)
        REFERENCES products(product_id)
);