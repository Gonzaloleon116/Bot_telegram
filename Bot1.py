import os
import threading
import re
import datetime
import pytz
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

# --- CONFIGURACIÓN ---
# Zona horaria (Cámbiala si tus usuarios son de otro país)
ZONA_HORARIA = 'America/Mexico_City'

# Temas por mes (Esto ayuda a filtrar el plan de lectura)
TEMAS_MENSUALES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

# --- SERVIDOR FALSO ---
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

# --- FUNCIÓN CENTRAL: GUARDAR HORARIO Y ACTIVAR ALARMA ---
async def guardar_y_activar_alarma(chat_id, hora_str, context):
    try:
        # 1. Guardar en Base de Datos
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Guardamos la hora. Si el usuario no existe, lo creamos con categoría default
        sql = """
            INSERT INTO usuarios (telegram_id, hora_recordatorio, categoria) 
            VALUES (%s, %s, 'joven') 
            ON DUPLICATE KEY UPDATE hora_recordatorio = %s
        """
        cursor.execute(sql, (chat_id, hora_str, hora_str))
        conn.commit()
        conn.close()

        # 2. Programar en Telegram (JobQueue)
        # Primero borramos alarmas viejas para no duplicar
        jobs_existentes = context.job_queue.get_jobs_by_name(str(chat_id))
        for job in jobs_existentes:
            job.schedule_removal()
            
        # Convertimos texto "07:00" a objeto de tiempo
        h, m = map(int, hora_str.split(':'))
        time_to_run = datetime.time(hour=h, minute=m, tzinfo=pytz.timezone(ZONA_HORARIA))
        
        # Agendamos
        context.job_queue.run_daily(enviar_recordatorio, time_to_run, chat_id=chat_id, name=str(chat_id))
        
        return True
    except Exception as e:
        print(f"Error programando: {e}")
        return False

# --- LÓGICA DE ENVÍO (MODIFICADA PARA LECTURA BÍBLICA) ---
async def enviar_recordatorio(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    telegram_id = job.chat_id
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Obtenemos datos del usuario
        cursor.execute("SELECT categoria FROM usuarios WHERE telegram_id = %s", (telegram_id,))
        res_cat = cursor.fetchone()
        
        if not res_cat:
            conn.close()
            return 
        
        categoria_usuario = res_cat[0]
        
        # Lógica del Plan de Lectura (Por Mes)
        mes_actual = datetime.datetime.now().month
        tema_del_mes = TEMAS_MENSUALES.get(mes_actual, "general")
        
        # Buscamos la lectura correspondiente
        # Ahora 'referencia' será el rango (Ej: Deut 1-4) y 'frase' un comentario motivacional
        sql = """
            SELECT frase, referencia FROM citas 
            WHERE categoria = %s AND (tema = %s OR tema = 'general')
            ORDER BY (tema = %s) DESC, RAND() 
            LIMIT 1
        """
        cursor.execute(sql, (categoria_usuario, tema_del_mes, tema_del_mes))
        lectura = cursor.fetchone()
        conn.close()
        
        if lectura:
            # lectura[0] = Comentario / Frase
            # lectura[1] = Rango de Lectura (Ej: Deuteronomio 1-4)
            msg = (
                f"🔔 **¡Hora de tu Lectura Diaria!**\n"
                f"📅 Plan de: *{tema_del_mes.capitalize()}*\n\n"
                f"📖 **Lectura de hoy:**\n"
                f"👉 `{lectura[1]}`\n\n"
                f"💭 _{lectura[0]}_"
            )
            await context.bot.send_message(chat_id=telegram_id, text=msg, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=telegram_id, text="¡Es hora de leer la Biblia! (Abre tu plan de lectura personal).")
            
    except Exception as e:
        print(f"Error enviando recordatorio a {telegram_id}: {e}")

# --- COMANDOS E INTERACCIÓN ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("👶 Niño", callback_data="cat_nino"),
        InlineKeyboardButton("🧑 Joven", callback_data="cat_joven"),
        InlineKeyboardButton("👨 Adulto", callback_data="cat_adulto")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 **¡Bienvenido a tu Plan Bíblico!**\n\n"
        "Este bot te ayudará a mantener tu hábito de lectura.\n"
        "Primero, elige tu categoría:", 
        reply_markup=reply_markup, 
        parse_mode="Markdown"
    )

# COMANDO /programar MEJORADO CON BOTONES
async def programar_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Si el usuario escribió la hora manualmente: /programar 07:00
    if context.args:
        hora_input = context.args[0]
        chat_id = update.effective_chat.id
        
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", hora_input):
            await update.message.reply_text("❌ Formato incorrecto. Usa HH:MM (ej: 07:00).")
            return

        exito = await guardar_y_activar_alarma(chat_id, hora_input, context)
        if exito:
            await update.message.reply_text(f"✅ ¡Listo! Alarma manual configurada a las **{hora_input}**.", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Error guardando la hora.")
        return

    # Si NO escribió hora, mostramos botones (UX Mejorada)
    keyboard = [
        [InlineKeyboardButton("🌅 06:00 AM", callback_data="time_06:00"), InlineKeyboardButton("☀️ 07:00 AM", callback_data="time_07:00")],
        [InlineKeyboardButton("🕗 08:00 AM", callback_data="time_08:00"), InlineKeyboardButton("🕘 09:00 AM", callback_data="time_09:00")],
        [InlineKeyboardButton("🌙 08:00 PM", callback_data="time_20:00"), InlineKeyboardButton("💤 09:00 PM", callback_data="time_21:00")],
        [InlineKeyboardButton("✏️ Escribir otra hora", callback_data="time_manual")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⏰ **Configura tu Recordatorio**\n\n"
        "Elige una hora rápida o escribe la tuya propia:", 
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# MANEJADOR UNIVERSAL DE BOTONES (Categorías y Horas)
async def manejar_botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.from_user.id

    # CASO 1: Selección de Categoría
    if data.startswith("cat_"):
        categoria = data.replace("cat_", "") # quitamos el prefijo
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            sql = "INSERT INTO usuarios (telegram_id, categoria) VALUES (%s, %s) ON DUPLICATE KEY UPDATE categoria = %s"
            cursor.execute(sql, (chat_id, categoria, categoria))
            conn.commit()
            conn.close()
            
            # Al elegir categoría, le sugerimos programar la hora inmediatamente
            await query.edit_message_text(
                f"✅ Categoría guardada: **{categoria.capitalize()}**.\n\n"
                "Ahora, configura a qué hora quieres leer:",
                parse_mode="Markdown"
            )
            # Llamamos a la función de programar para mostrar los botones de hora ahí mismo
            # (Truco: pasamos argumentos vacíos para que muestre el menú)
            context.args = []
            await programar_horario(update, context)
            
        except Exception:
            await query.edit_message_text("❌ Error guardando categoría.")

    # CASO 2: Selección de Hora (Botones rápidos)
    elif data.startswith("time_"):
        hora = data.replace("time_", "")
        
        if hora == "manual":
            await query.edit_message_text("✏️ Escribe el comando así:\n`/programar 15:30` (para las 3:30 PM)", parse_mode="Markdown")
            return

        exito = await guardar_y_activar_alarma(chat_id, hora, context)
        if exito:
            await query.edit_message_text(f"✅ ¡Excelente! Te recordaré leer la biblia todos los días a las **{hora}**.", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Hubo un error al guardar la hora.")

# --- RESTAURACIÓN AL INICIAR ---
async def restaurar_alarmas(application):
    print("🔄 Restaurando alarmas...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id, hora_recordatorio FROM usuarios WHERE hora_recordatorio IS NOT NULL")
        usuarios = cursor.fetchall()
        conn.close()
        
        count = 0
        for uid, hora_str in usuarios:
            try:
                h, m = map(int, hora_str.split(':'))
                tz = pytz.timezone(ZONA_HORARIA)
                time_to_run = datetime.time(hour=h, minute=m, tzinfo=tz)
                application.job_queue.run_daily(enviar_recordatorio, time_to_run, chat_id=uid, name=str(uid))
                count += 1
            except Exception: pass
        print(f"✅ {count} alarmas activas.")
    except Exception as e:
        print(f"❌ Error restaurando: {e}")

def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN: return

    threading.Thread(target=start_dummy_server, daemon=True).start()
    
    req = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0, http_version="1.1")
    
    async def post_init(application):
        await restaurar_alarmas(application)

    app = ApplicationBuilder().token(TOKEN).request(req).post_init(post_init).build()
    
    # Handlers
    app.add_handler(CommandHandler(["start", "Iniciar"], start))
    app.add_handler(CommandHandler("programar", programar_horario))
    # Un solo CallbackQueryHandler maneja TODO (categorías y horas)
    app.add_handler(CallbackQueryHandler(manejar_botones))

    print("Bot corriendo con Plan de Lectura...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
