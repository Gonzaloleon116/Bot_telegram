import os
import threading
import re
from http.server import SimpleHTTPRequestHandler, HTTPServer
import mysql.connector
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
from telegram.request import HTTPXRequest

# --- SERVIDOR FALSO PARA RENDER ---
def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("", port), SimpleHTTPRequestHandler)
    print(f"🖥️ Servidor falso corriendo en el puerto {port}")
    server.serve_forever()

# --- CONEXIÓN DB ---
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=os.getenv("MYSQLPORT")
    )

# --- MIGRACIÓN DB (Si ya la corriste una vez, no borrará nada si la estructura ya es correcta) ---
def setup_database():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS citas (
            id INT AUTO_INCREMENT PRIMARY KEY,
            frase TEXT NOT NULL,
            referencia VARCHAR(255) NOT NULL,
            categoria VARCHAR(50) NOT NULL
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            telegram_id BIGINT PRIMARY KEY,
            categoria VARCHAR(50)
        )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error setup: {e}")

# --- LIMPIADOR ---
def limpiar_texto(texto):
    return re.sub(r'[^\w\s]', '', str(texto)).lower().strip()

# --- COMANDOS BÁSICOS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("👶 Niño", callback_data="nino"),
        InlineKeyboardButton("🧑 Joven", callback_data="joven"),
        InlineKeyboardButton("👨 Adulto", callback_data="adulto")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📖 Bienvenido. Elige tu categoría:", reply_markup=reply_markup)

async def enviar_cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT categoria FROM usuarios WHERE telegram_id = %s", (telegram_id,))
        res = cursor.fetchone()
        
        if not res:
            await update.message.reply_text("⚠️ Usa /start primero.")
            conn.close()
            return
            
        cursor.execute("SELECT frase, referencia FROM citas WHERE categoria = %s ORDER BY RAND() LIMIT 1", (res[0],))
        cita = cursor.fetchone()
        conn.close()
        
        if cita:
            await update.message.reply_text(f"✨ {cita[0]}\n\n📖 {cita[1]}")
        else:
            await update.message.reply_text("No hay citas para esta categoría.")
    except Exception as e:
        await update.message.reply_text("❌ Error de conexión.")

# --- MANEJADOR DE CATEGORÍAS (Cuando el usuario elige Niño/Joven/Adulto) ---
async def seleccionar_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    categoria = query.data
    telegram_id = query.from_user.id
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        sql = "INSERT INTO usuarios (telegram_id, categoria) VALUES (%s, %s) ON DUPLICATE KEY UPDATE categoria = %s"
        cursor.execute(sql, (telegram_id, categoria, categoria))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ Categoría guardada: {categoria.capitalize()}\nUsa /cita para leer.")
    except Exception as e:
        await query.edit_message_text("❌ Error guardando preferencia.")

# --- LÓGICA DE AGREGAR CITA (CON CONFIRMACIÓN) ---
async def agregar_cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv("ADMIN_ID")
    
    if not admin_id or str(user_id).strip() != str(admin_id).strip():
        await update.message.reply_text("⛔ Sin permiso.")
        return

    try:
        entrada = ' '.join(context.args)
        if "|" not in entrada:
            await update.message.reply_text("⚠️ Formato: `/agregar cat Frase | Referencia`", parse_mode="Markdown")
            return

        # Separar datos
        partes = entrada.split(' ', 1)
        categoria = partes[0].lower()
        resto = partes[1]
        
        if categoria not in ['nino', 'joven', 'adulto']:
            await update.message.reply_text("❌ Categoría inválida.")
            return

        frase_in, ref_in = resto.split("|", 1)
        frase_in = frase_in.strip()
        ref_in = ref_in.strip()

        # --- VALIDACIÓN DE DUPLICADOS ---
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT frase, referencia FROM citas")
        todas = cursor.fetchall()
        conn.close()

        input_f_clean = limpiar_texto(frase_in)
        input_r_clean = limpiar_texto(ref_in)

        advertencia = ""
        
        for db_frase, db_ref in todas:
            db_f_clean = limpiar_texto(db_frase)
            db_r_clean = limpiar_texto(db_ref)

            # 1. Duplicado EXACTO (Misma frase Y misma cita) -> BLOQUEAR
            if input_f_clean == db_f_clean and input_r_clean == db_r_clean:
                await update.message.reply_text("⛔ **Error:** Esta cita ya existe idéntica. No se guardó.", parse_mode="Markdown")
                return # Se acaba aquí.

            # 2. Similitud Parcial (Misma frase O misma cita) -> ADVERTENCIA
            if input_f_clean == db_f_clean:
                advertencia = f"⚠️ La frase ya existe en: '{db_ref}'"
            elif input_r_clean == db_r_clean:
                advertencia = f"⚠️ La referencia ya existe con: '{db_frase}'"

        # --- TOMA DE DECISIÓN ---
        if advertencia:
            # Si hay advertencia, NO guardamos todavía. Pedimos confirmación.
            
            # Guardamos los datos en la "memoria temporal" del usuario
            context.user_data['temp_cita'] = {
                'frase': frase_in,
                'ref': ref_in,
                'cat': categoria
            }

            keyboard = [[
                InlineKeyboardButton("✅ Sí, guardar", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ Cancelar", callback_data="confirm_no")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"{advertencia}\n\n¿Estás seguro de que quieres guardarla de todos modos?",
                reply_markup=reply_markup
            )
        else:
            # Si NO hay advertencia, guardamos directo
            guardar_en_db(frase_in, ref_in, categoria)
            await update.message.reply_text(f"✅ Guardado exitoso en **{categoria}**.", parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# --- NUEVO: FUNCIÓN QUE EJECUTA EL GUARDADO FINAL ---
def guardar_en_db(frase, referencia, categoria):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO citas (frase, referencia, categoria) VALUES (%s, %s, %s)", (frase, referencia, categoria))
        conn.commit()
        conn.close()
        return True
    except:
        return False

# --- NUEVO: MANEJADOR DE LOS BOTONES DE CONFIRMACIÓN ---
async def manejar_confirmacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_no":
        await query.edit_message_text("❌ Operación cancelada. No se guardó nada.")
        # Limpiamos la memoria
        context.user_data.pop('temp_cita', None)
        return

    if query.data == "confirm_yes":
        # Recuperamos los datos de la memoria
        datos = context.user_data.get('temp_cita')
        
        if not datos:
            await query.edit_message_text("⚠️ Error: Los datos expiraron. Intenta agregarlo de nuevo.")
            return
            
        guardar_en_db(datos['frase'], datos['ref'], datos['cat'])
        await query.edit_message_text(f"✅ **Guardado forzado** en {datos['cat']}:\n\n📝 {datos['frase']}\n📖 {datos['ref']}", parse_mode="Markdown")
        context.user_data.pop('temp_cita', None)

# --- FUNCIÓN DE EMERGENCIA PARA ARREGLAR LA TABLA ---
async def reset_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv("ADMIN_ID")
    
    # Solo tú puedes usar esto
    if str(user_id).strip() != str(admin_id).strip():
        await update.message.reply_text("⛔ No tienes permiso para reiniciar la base de datos.")
        return

    await update.message.reply_text("⚠️ Iniciando reparación de la base de datos... Espera.")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Borramos la tabla defectuosa
        cursor.execute("DROP TABLE IF EXISTS citas")
        
        # 2. La creamos de nuevo (limpia y con las columnas correctas)
        cursor.execute("""
        CREATE TABLE citas (
            id INT AUTO_INCREMENT PRIMARY KEY,
            frase TEXT NOT NULL,
            referencia VARCHAR(255) NOT NULL,
            categoria VARCHAR(50) NOT NULL
        )
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        await update.message.reply_text("✅ **¡Éxito!** La tabla 'citas' ha sido reconstruida.\nAhora intenta usar /agregar de nuevo.")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Falló la reparación: {e}")
        
def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN: return

    setup_database()
    threading.Thread(target=start_dummy_server, daemon=True).start()
    
    req = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0, http_version="1.1")
    app = ApplicationBuilder().token(TOKEN).request(req).build()
    
    # --- HANDLERS ORDENADOS ---
    app.add_handler(CommandHandler(["start", "Iniciar"], start))
    app.add_handler(CommandHandler("cita", enviar_cita))
    app.add_handler(CommandHandler("agregar", agregar_cita))

    app.add_handler(CommandHandler("reset", reset_db))
    # Handler específico para categorías (nino, joven, adulto)
    app.add_handler(CallbackQueryHandler(seleccionar_categoria, pattern='^(nino|joven|adulto)$'))
    
    # Handler específico para confirmación (confirm_yes, confirm_no)
    app.add_handler(CallbackQueryHandler(manejar_confirmacion, pattern='^confirm_'))
    
    print("Bot corriendo...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()

