import os
import mysql.connector
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
from telegram.request import HTTPXRequest

# --- CONEXIÓN A BASE DE DATOS ---
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=os.getenv("MYSQLPORT")
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("👶 Niño", callback_data="nino"),
        InlineKeyboardButton("🧑 Joven", callback_data="joven"),
        InlineKeyboardButton("👨 Adulto", callback_data="adulto")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📖 Bienvenido. Elige tu categoría:", reply_markup=reply_markup)

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
        cursor.close()
        conn.close()
        await query.edit_message_text(f"✅ Categoría guardada: {categoria.capitalize()}\nUsa /cita para leer.")
    except Exception as e:
        print(f"Error DB: {e}")
        await query.edit_message_text("❌ Error guardando preferencia.")

async def enviar_cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT categoria FROM usuarios WHERE telegram_id = %s", (telegram_id,))
        resultado = cursor.fetchone()
        if not resultado:
            await update.message.reply_text("⚠️ Usa /start primero.")
            conn.close()
            return
        
        cursor.execute("SELECT texto FROM citas WHERE categoria = %s ORDER BY RAND() LIMIT 1", (resultado[0],))
        cita = cursor.fetchone()
        conn.close()
        
        if cita:
            await update.message.reply_text(f"✨ {cita[0]}")
        else:
            await update.message.reply_text("No hay citas para esta categoría.")
    except Exception as e:
        print(f"Error Cita: {e}")
        await update.message.reply_text("❌ Error de conexión.")

async def agregar_cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv("ADMIN_ID")
    if str(user_id) != str(admin_id):
        await update.message.reply_text("⛔ Sin permiso.")
        return
    try:
        if len(context.args) < 2: return await update.message.reply_text("Uso: /agregar [cat] [texto]")
        cat = context.args[0].lower()
        texto = ' '.join(context.args[1:])
        if cat not in ['nino', 'joven', 'adulto']: return await update.message.reply_text("Categoría inválida.")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO citas (texto, categoria) VALUES (%s, %s)", (texto, cat))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Cita guardada en {cat}.")
    except Exception as e:
        await update.message.reply_text("❌ Error al guardar.")

def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN: 
        print("Error: Falta TOKEN")
        return

    # --- AQUÍ ESTÁ EL TRUCO ---
    # Forzamos HTTP 1.1. Esto suele saltarse el bloqueo de Railway.
    req = HTTPXRequest(
        connect_timeout=60.0, 
        read_timeout=60.0, 
        http_version="1.1"
    )
    
    app = ApplicationBuilder().token(TOKEN).request(req).build()
    
    app.add_handler(CommandHandler(["start", "Iniciar"], start))
    app.add_handler(CommandHandler("cita", enviar_cita))
    app.add_handler(CallbackQueryHandler(seleccionar_categoria))
    app.add_handler(CommandHandler("agregar", agregar_cita))
    
    print("Bot corriendo con MySQL...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
