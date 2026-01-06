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
ZONA_HORARIA = 'America/Mexico_City'

# --- 1. SERVIDOR FALSO ---
def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("", port), SimpleHTTPRequestHandler)
    print(f"🖥️ Servidor falso corriendo en el puerto {port}")
    server.serve_forever()

# --- 2. CONEXIÓN BASE DE DATOS ---
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=os.getenv("MYSQLPORT")
    )

# --- 3. LÓGICA DE ALARMA DIARIA ---
async def enviar_recordatorio(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    telegram_id = job.chat_id
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # A. Categoría
        cursor.execute("SELECT categoria FROM usuarios WHERE telegram_id = %s", (telegram_id,))
        res_cat = cursor.fetchone()
        
        if not res_cat:
            conn.close()
            return 
        
        categoria_usuario = res_cat[0]
        
        # B. Fecha
        ahora = datetime.datetime.now(pytz.timezone(ZONA_HORARIA))
        mes_actual = ahora.month
        dia_actual = ahora.day
        
        # C. Consulta Relacional
        sql = """
            SELECT libros.nombre, plan_lectura.capitulos, plan_lectura.mensaje
            FROM plan_lectura
            INNER JOIN libros ON plan_lectura.libro_id = libros.id
            WHERE plan_lectura.categoria = %s AND plan_lectura.mes = %s AND plan_lectura.dia = %s
            LIMIT 1
        """
        
        cursor.execute(sql, (categoria_usuario, mes_actual, dia_actual))
        resultado = cursor.fetchone()
        conn.close()
        
        if resultado:
            msg = (
                f"🔔 **Plan Diario - {dia_actual}/{mes_actual}**\n\n"
                f"📖 **Lectura de hoy:**\n👉 *{resultado[0]} {resultado[1]}*\n\n"
                f"💭 _{resultado[2]}_"
            )
            await context.bot.send_message(chat_id=telegram_id, text=msg, parse_mode="Markdown")
        else:
            await context.bot.send_message(
                chat_id=telegram_id, 
                text=f"📅 Hoy es {dia_actual}/{mes_actual}. No hay plan cargado para hoy."
            )
            
    except Exception as e:
        print(f"Error alarma {telegram_id}: {e}")

# --- 4. GUARDAR HORARIO Y ACTIVAR ---
async def guardar_y_activar_alarma(chat_id, hora_str, context):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        sql = """
            INSERT INTO usuarios (telegram_id, hora_recordatorio, categoria) 
            VALUES (%s, %s, 'joven') 
            ON DUPLICATE KEY UPDATE hora_recordatorio = %s
        """
        cursor.execute(sql, (chat_id, hora_str, hora_str))
        conn.commit()
        conn.close()

        jobs_existentes = context.job_queue.get_jobs_by_name(str(chat_id))
        for job in jobs_existentes: job.schedule_removal()
            
        h, m = map(int, hora_str.split(':'))
        time_to_run = datetime.time(hour=h, minute=m, tzinfo=pytz.timezone(ZONA_HORARIA))
        
        context.job_queue.run_daily(enviar_recordatorio, time_to_run, chat_id=chat_id, name=str(chat_id))
        return True, ""
    except Exception as e:
        return False, str(e)

# --- 5. COMANDOS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("👶 Niño", callback_data="cat_nino"),
        InlineKeyboardButton("🧑 Joven", callback_data="cat_joven"),
        InlineKeyboardButton("👨 Adulto", callback_data="cat_adulto")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    mensaje = (
        "👋 **¡Bienvenido a tu Asistente Bíblico!**\n\n"
        "🛠 **Comandos:**\n"
        "🔹 `/cita` → Versículo aleatorio.\n"
        "🔹 `/programar` → Configurar alarma.\n\n"
        "👇 **Elige tu etapa para comenzar:**"
    )
    await update.message.reply_text(mensaje, reply_markup=reply_markup, parse_mode="Markdown")

async def enviar_cita_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await update.message.reply_text(f"✨ **Versículo Ánimo:**\n\n_{cita[0]}_\n📖 {cita[1]}", parse_mode="Markdown")
        else:
            await update.message.reply_text("No hay versículos disponibles.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error DB: {str(e)}")

async def programar_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        hora_input = context.args[0]
        chat_id = update.effective_chat.id
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", hora_input):
            await update.message.reply_text("❌ Formato incorrecto. Usa HH:MM.")
            return

        exito, error_msg = await guardar_y_activar_alarma(chat_id, hora_input, context)
        if exito:
            await update.message.reply_text(f"✅ Alarma configurada: **{hora_input}**.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ Error Técnico:\n`{error_msg}`", parse_mode="Markdown")
        return

    # Menú de horas (para el comando escrito)
    keyboard = [
        [InlineKeyboardButton("🌅 06:00 AM", callback_data="time_06:00"), InlineKeyboardButton("☀️ 07:00 AM", callback_data="time_07:00")],
        [InlineKeyboardButton("🕗 08:00 AM", callback_data="time_08:00"), InlineKeyboardButton("🌙 09:00 PM", callback_data="time_21:00")],
        [InlineKeyboardButton("✏️ Manual", callback_data="time_manual")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("⏰ **Elige hora de lectura:**", reply_markup=reply_markup, parse_mode="Markdown")


async def manejar_botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.from_user.id

    # CASO 1: EL USUARIO ELIGIÓ CATEGORÍA
    if data.startswith("cat_"):
        categoria = data.replace("cat_", "")
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 1. Guardamos la categoría en la BD
            # Usamos ON DUPLICATE KEY para que si ya existe, solo la actualice
            sql = "INSERT INTO usuarios (telegram_id, categoria) VALUES (%s, %s) ON DUPLICATE KEY UPDATE categoria = %s"
            cursor.execute(sql, (chat_id, categoria, categoria))
            conn.commit()
            conn.close()
            
            # 2. DEFINIMOS EL TECLADO DEL RELOJ AQUÍ MISMO (Para evitar el error NoneType)
            keyboard_horas = [
                [InlineKeyboardButton("🌅 06:00 AM", callback_data="time_06:00"), InlineKeyboardButton("☀️ 07:00 AM", callback_data="time_07:00")],
                [InlineKeyboardButton("🕗 08:00 AM", callback_data="time_08:00"), InlineKeyboardButton("🌙 09:00 PM", callback_data="time_21:00")],
                [InlineKeyboardButton("✏️ Manual", callback_data="time_manual")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard_horas)
            
            # 3. Editamos el mensaje original (ESTO ES LO QUE ARREGLA EL ERROR)
            await query.edit_message_text(
                f"✅ Categoría guardada: **{categoria.capitalize()}**.\n\n"
                "⏰ **Ahora configura tu hora de lectura:**", 
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            # Si falla la base de datos, te avisará aquí
            print(f"ERROR SQL: {e}")
            await query.edit_message_text(f"❌ Error Base de Datos:\n`{str(e)}`", parse_mode="Markdown")

    # CASO 2: EL USUARIO ELIGIÓ HORA
    elif data.startswith("time_"):
        hora = data.replace("time_", "")
        
        if hora == "manual":
            await query.edit_message_text("✏️ Escribe el comando así:\n`/programar 07:30`", parse_mode="Markdown")
            return
        
        # Llamamos a la función de lógica interna (no a la del comando)
        exito, error_msg = await guardar_y_activar_alarma(chat_id, hora, context)
        
        if exito:
            await query.edit_message_text(f"✅ ¡Excelente! Te recordaré leer la biblia todos los días a las **{hora}**.", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"❌ Error al guardar hora:\n`{error_msg}`", parse_mode="Markdown")
# --- 7. RESTAURACIÓN ---
async def restaurar_alarmas(application):
    print("🔄 Restaurando alarmas...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id, hora_recordatorio FROM usuarios WHERE hora_recordatorio IS NOT NULL")
        usuarios = cursor.fetchall()
        conn.close()
        for uid, hora_str in usuarios:
            try:
                h, m = map(int, hora_str.split(':'))
                tz = pytz.timezone(ZONA_HORARIA)
                time_to_run = datetime.time(hour=h, minute=m, tzinfo=tz)
                application.job_queue.run_daily(enviar_recordatorio, time_to_run, chat_id=uid, name=str(uid))
            except: pass
    except: pass

def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN: return

    threading.Thread(target=start_dummy_server, daemon=True).start()
    req = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0, http_version="1.1")
    
    async def post_init(application): await restaurar_alarmas(application)

    app = ApplicationBuilder().token(TOKEN).request(req).post_init(post_init).build()
    
    app.add_handler(CommandHandler(["start", "Iniciar"], start))
    app.add_handler(CommandHandler("cita", enviar_cita_random))
    app.add_handler(CommandHandler("programar", programar_horario))
    app.add_handler(CallbackQueryHandler(manejar_botones))

    print("Bot corriendo - Versión Final Corregida...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
