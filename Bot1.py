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

# --- 1. SERVIDOR FALSO (Para mantener vivo a Render) ---
def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("", port), SimpleHTTPRequestHandler)
    print(f"🖥️ Servidor falso corriendo en el puerto {port}")
    server.serve_forever()

# --- 2. CONEXIÓN A BASE DE DATOS ---
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=os.getenv("MYSQLPORT")
    )

# --- 3. UTILIDADES ---
def limpiar_texto(texto):
    # Quita símbolos para comparar duplicados (ej: "Juan 3:16" == "(Juan 3:16)")
    return re.sub(r'[^\w\s]', '', str(texto)).lower().strip()

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

# --- 4. COMANDOS DEL BOT ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("👶 Niño", callback_data="nino"),
        InlineKeyboardButton("🧑 Joven", callback_data="joven"),
        InlineKeyboardButton("👨 Adulto", callback_data="adulto")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📖 Bienvenido al Bot de Citas Bíblicas.\nElige una categoría:", reply_markup=reply_markup)

async def enviar_cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verificamos qué preferencia tiene el usuario
        cursor.execute("SELECT categoria FROM usuarios WHERE telegram_id = %s", (telegram_id,))
        res = cursor.fetchone()
        
        if not res:
            await update.message.reply_text("⚠️ Primero elige una categoría usando /start")
            conn.close()
            return
            
        # Buscamos una cita aleatoria de esa categoría
        cursor.execute("SELECT frase, referencia FROM citas WHERE categoria = %s ORDER BY RAND() LIMIT 1", (res[0],))
        cita = cursor.fetchone()
        conn.close()
        
        if cita:
            await update.message.reply_text(f"✨ {cita[0]}\n\n📖 {cita[1]}")
        else:
            await update.message.reply_text(f"Aún no hay citas para la categoría: {res[0]}.")
    except Exception as e:
        print(f"Error enviando cita: {e}")
        await update.message.reply_text("❌ Error de conexión temporal.")

async def seleccionar_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Verificar si es una confirmación de guardado o selección de categoría
    if query.data.startswith("confirm_"):
        return # Dejamos que lo maneje la otra función
        
    await query.answer()
    categoria = query.data
    telegram_id = query.from_user.id
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Guardamos la preferencia del usuario
        sql = "INSERT INTO usuarios (telegram_id, categoria) VALUES (%s, %s) ON DUPLICATE KEY UPDATE categoria = %s"
        cursor.execute(sql, (telegram_id, categoria, categoria))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ Categoría seleccionada: {categoria.capitalize()}\n\nUsa /cita para recibir una palabra.")
    except Exception as e:
        await query.edit_message_text("❌ Error al guardar tu selección.")

async def agregar_cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_id = os.getenv("ADMIN_ID")
    
    # Validación de Administrador
    if not admin_id or str(user_id).strip() != str(admin_id).strip():
        await update.message.reply_text("⛔ No tienes permiso para agregar citas.")
        return

    try:
        entrada = ' '.join(context.args)
        if "|" not in entrada:
            await update.message.reply_text(
                "⚠️ **Formato Incorrecto**\nUsa: `/agregar [categoria] [Frase] | [Referencia]`\n\nEjemplo:\n`/agregar joven Todo lo puedo | Filipenses 4:13`", 
                parse_mode="Markdown"
            )
            return

        # Separación de datos
        partes = entrada.split(' ', 1)
        categoria = partes[0].lower()
        resto = partes[1]
        
        if categoria not in ['nino', 'joven', 'adulto']:
            await update.message.reply_text("❌ Categoría inválida. Usa: nino, joven o adulto.")
            return

        frase_in, ref_in = resto.split("|", 1)
        frase_in = frase_in.strip()
        ref_in = ref_in.strip()

        # Validación de Duplicados
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

            # 1. Duplicado EXACTO -> Bloqueo
            if input_f_clean == db_f_clean and input_r_clean == db_r_clean:
                await update.message.reply_text("⛔ **Error:** Esta cita ya existe idéntica en la base de datos.", parse_mode="Markdown")
                return

            # 2. Similitud Parcial -> Advertencia con Botones
            if input_f_clean == db_f_clean:
                advertencia = f"⚠️ La frase ya existe en: '{db_ref}'"
            elif input_r_clean == db_r_clean:
                advertencia = f"⚠️ La referencia ya existe con: '{db_frase}'"

        if advertencia:
            # Guardar en memoria temporal y pedir confirmación
            context.user_data['temp_cita'] = {'frase': frase_in, 'ref': ref_in, 'cat': categoria}
            keyboard = [[
                InlineKeyboardButton("✅ Sí, guardar", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ Cancelar", callback_data="confirm_no")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(f"{advertencia}\n\n¿Quieres guardarla de todos modos?", reply_markup=reply_markup)
        else:
            # Guardar directo
            if guardar_en_db(frase_in, ref_in, categoria):
                await update.message.reply_text(f"✅ Guardado en **{categoria}**.", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Error al escribir en la base de datos.")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def manejar_confirmacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_no":
        await query.edit_message_text("❌ Operación cancelada.")
        context.user_data.pop('temp_cita', None)
        return

    if query.data == "confirm_yes":
        datos = context.user_data.get('temp_cita')
        if not datos:
            await query.edit_message_text("⚠️ Error: Datos expirados.")
            return
            
        guardar_en_db(datos['frase'], datos['ref'], datos['cat'])
        await query.edit_message_text(f"✅ **Guardado forzado** en {datos['cat']}.", parse_mode="Markdown")
        context.user_data.pop('temp_cita', None)

def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN: return

    # Iniciamos servidor falso para Render
    threading.Thread(target=start_dummy_server, daemon=True).start()
    
    # Configuración de red para evitar bloqueos
    req = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0, http_version="1.1")
    app = ApplicationBuilder().token(TOKEN).request(req).build()
    
    # Handlers
    app.add_handler(CommandHandler(["start", "Iniciar"], start))
    app.add_handler(CommandHandler("cita", enviar_cita))
    app.add_handler(CommandHandler("agregar", agregar_cita))
    app.add_handler(CallbackQueryHandler(seleccionar_categoria, pattern='^(nino|joven|adulto)$'))
    app.add_handler(CallbackQueryHandler(manejar_confirmacion, pattern='^confirm_'))
    
    print("Bot corriendo con MySQL (Modo Seguro)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
