-- =============================================================================
-- PopeNails - Tabla de Tarjetas de Fidelización en Supabase
-- Ejecuta este script en el SQL Editor de tu proyecto Supabase (ktmwjuamovupzwqifmct)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loyalty_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT now(),
    client_name TEXT NOT NULL UNIQUE,
    phone TEXT,
    stamps INTEGER DEFAULT 0 CHECK (stamps >= 0 AND stamps <= 10),
    points INTEGER DEFAULT 0 CHECK (points >= 0),
    last_visit TIMESTAMPTZ DEFAULT now(),
    total_cycles_completed INTEGER DEFAULT 0
);

-- Habilitar Row Level Security (RLS)
ALTER TABLE loyalty_cards ENABLE ROW LEVEL SECURITY;

-- Políticas de acceso para clientes y salón mediante anon key
CREATE POLICY "Permitir lectura publica de tarjetas" 
ON loyalty_cards FOR SELECT USING (true);

CREATE POLICY "Permitir crear tarjetas" 
ON loyalty_cards FOR INSERT WITH CHECK (true);

CREATE POLICY "Permitir actualizar sellos y puntos" 
ON loyalty_cards FOR UPDATE USING (true);

CREATE POLICY "Permitir eliminar tarjetas" 
ON loyalty_cards FOR DELETE USING (true);

-- Índices de búsqueda rápida
CREATE INDEX IF NOT EXISTS idx_loyalty_cards_client_name ON loyalty_cards(client_name);
CREATE INDEX IF NOT EXISTS idx_loyalty_cards_phone ON loyalty_cards(phone);
