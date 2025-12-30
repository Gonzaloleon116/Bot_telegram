import os
import mysql.connector
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
# Importamos HTTPXRequest para configurar la conexión avanzada
from telegram.request import HTTPXRequest

# --- 1. FUNCIÓN PARA CONECTARSE A LA BASE DE DATOS ---
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

    await update.message.reply_text(
        "📖 Bienvenido al Bot de Citas Bíblicas\n\n"
        "Elige tu categoría:",
        reply_markup=reply_markup
    )

async def seleccionar_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    categoria = query.data
    telegram_id = query.from_user.id

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        sql = """
        INSERT INTO usuarios (telegram_id, categoria) 
        VALUES (%s, %s) 
        ON DUPLICATE KEY UPDATE categoria = %s
        """
        cursor.execute(sql, (telegram_id, categoria, categoria))
        conn.commit()

        cursor.close()
        conn.close()

        await query.edit_message_text(
            f"✅ Categoría guardada: {categoria.capitalize()}\n\n"
            "Escribe /cita para recibir una palabra de Dios."
        )
    except Exception as e:
        print(f"Error en base de datos: {e}")
        await query.edit_message_text("❌ Hubo un error guardando tu preferencia.")

async def enviar_cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT categoria FROM usuarios WHERE telegram_id = %s", (telegram_id,))
        resultado = cursor.fetchone()

        if not resultado:
            await update.message.reply_text("⚠️ No has elegido categoría. Usa /start primero.")
            cursor.close()
            conn.close()
            return

        categoria_usuario = resultado[0]

        cursor.execute(
            "SELECT texto FROM citas WHERE categoria = %s ORDER BY RAND() LIMIT 1", 
            (categoria_usuario,)
        )
        cita_resultado = cursor.fetchone()

        cursor.close()
        conn.close()

        if cita_resultado:
            await update.message.reply_text(f"✨ {cita_resultado[0]}")
        else:
            await update.message.reply_text("No encontré citas para tu categoría.")

    except Exception as e:
        print(f"Error obteniendo cita: {e}")
        await update.message.reply_text("❌ Error de conexión con la base de datos.")

async def agregar_cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv("ADMIN_ID")

    if str(user_id) != str(admin_id):
        await update.message.reply_text("⛔ No tienes permiso para usar este comando.")
        return

    try:
        if len(context.args) < 2:
            await update.message.reply_text("⚠️ Uso: /agregar [nino/joven/adulto] [Texto]")
            return

        categoria = context.args[0].lower()
        texto_cita = ' '.join(context.args[1:])

        if categoria not in ['nino', 'joven', 'adulto']:
            await update.message.reply_text("❌ Categoría inválida. Usa: nino, joven o adulto.")
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        sql = "INSERT INTO citas (texto, categoria) VALUES (%s, %s)"
        cursor.execute(sql, (texto_cita, categoria))
        conn.commit()

        cursor.close()
        conn.close()

        await update.message.reply_text(f"✅ ¡Cita guardada en **{categoria}**!")

    except Exception as e:
        print(f"Error agregando cita: {e}")
        await update.message.reply_text("❌ Ocurrió un error al intentar guardar.")

def main():
    TOKEN = os.getenv("TOKEN") 
    if not TOKEN:
        print("Error: No se encontró el TOKEN")
        return

    # --- CONFIGURACIÓN DE CONEXIÓN CORREGIDA ---
    request_config = HTTPXRequest(
        connect_timeout=60.0,
        read_timeout=60.0,
        http_version="1.1"
    )

    app = ApplicationBuilder().token(TOKEN).request(request_config).build()

    app.add_handler(CommandHandler(["start", "Iniciar"], start))
    app.add_handler(CommandHandler("cita", enviar_cita))
    app.add_handler(CallbackQueryHandler(seleccionar_categoria))
    app.add_handler(CommandHandler("agregar", agregar_cita))

    print("Bot corriendo con MySQL...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
