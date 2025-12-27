import os
import mysql.connector
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# --- 1. FUNCIÓN PARA CONECTARSE A LA BASE DE DATOS ---
def get_db_connection():
    # Railway inyecta estas variables automáticamente en tu entorno
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
    
    # --- 2. GUARDAMOS AL USUARIO EN LA BASE DE DATOS (INSERT / UPDATE) ---
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Esta consulta guarda al usuario, o actualiza su categoría si ya existía
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
        
        # A. Primero averiguamos qué categoría eligió este usuario
        cursor.execute("SELECT categoria FROM usuarios WHERE telegram_id = %s", (telegram_id,))
        resultado = cursor.fetchone()
        
        if not resultado:
            await update.message.reply_text("⚠️ No has elegido categoría. Usa /start primero.")
            cursor.close()
            conn.close()
            return
            
        categoria_usuario = resultado[0]
        
        # B. Buscamos UNA cita aleatoria de esa categoría
        # ORDER BY RAND() elige una al azar de la tabla
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

def main():
    TOKEN = os.getenv("TOKEN") 
    if not TOKEN:
        print("Error: No se encontró el TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler(["start", "Iniciar"], start))
    app.add_handler(CommandHandler("cita", enviar_cita))
    app.add_handler(CallbackQueryHandler(seleccionar_categoria))
    
    print("Bot corriendo con MySQL...")
    app.run_polling()

if __name__ == "__main__":
    main()
