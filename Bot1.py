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

# --- SERVIDOR FALSO ---
def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("", port), SimpleHTTPRequestHandler)
    print(f"🖥️ Servidor falso corriendo en el puerto {port}")
    server.serve_forever()

# --- BASE DE DATOS ---
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
    
    # 1. Seguridad
    if not admin_id or str(user_id).strip() != str(admin_id).strip():
        await update.message.reply_text("⛔ Sin permiso de administrador.")
        return

    try:
        if len(context.args) < 2: 
            await update.message.reply_text("⚠️ Uso: /agregar [cat] [Cita Biblica]")
            return
            
        cat = context.args[0].lower()
        texto_completo = ' '.join(context.args[1:])
        
        # 2. Validación de Categoría
        if cat not in ['nino', 'joven', 'adulto']: 
            await update.message.reply_text("❌ Categoría inválida. Usa: nino, joven, adulto")
            return
        
        # 3. Validación de Formato (Capítulo:Versículo)
        if not re.search(r"\d+:\d+", texto_completo):
            await update.message.reply_text("❌ Error: Falta la referencia (Ej: Juan 3:16)")
            return
        
        # --- AQUÍ EMPIEZA LA CONEXIÓN ---
        conn = get_db_connection()
        cursor = conn.cursor()

        # 4. VALIDACIÓN DE DUPLICADOS (NUEVO)
        # Buscamos si existe EXACTAMENTE el mismo texto
        sql_check = "SELECT id FROM citas WHERE texto = %s"
        cursor.execute(sql_check, (texto_completo,))
        resultado = cursor.fetchone()

        if resultado:
            # Si encontró algo, detenemos todo
            await update.message.reply_text("⚠️ **Atención:** Esa cita ya existe en la base de datos. No se guardó.")
            cursor.close()
            conn.close()
            return # <-- Esto saca al bot de la función para que no guarde nada

        # 5. Si no existe, guardamos
        sql_insert = "INSERT INTO citas (texto, categoria) VALUES (%s, %s)"
        cursor.execute(sql_insert, (texto_completo, cat))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        await update.message.reply_text(f"✅ ¡Cita guardada correctamente en **{cat}**!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error Técnico: {str(e)}")

def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN: 
        print("Error: Falta TOKEN")
        return

    threading.Thread(target=start_dummy_server, daemon=True).start()

    req = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0, http_version="1.1")
    
    app = ApplicationBuilder().token(TOKEN).request(req).build()
    
    app.add_handler(CommandHandler(["start", "Iniciar"], start))
    app.add_handler(CommandHandler("cita", enviar_cita))
    app.add_handler(CallbackQueryHandler(seleccionar_categoria))
    app.add_handler(CommandHandler("agregar", agregar_cita))
    
    print("Bot corriendo con MySQL...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
