import imaplib
import email
from email.header import decode_header
import os
import google.generativeai as genai
from taller.models import OrdenDeReparacion, ReporteEscaner

# --- CREDENCIALES DEL ESCÁNER ---
CORREO_TALLER = "servimaxm7@gmail.com"
PASSWORD_APP = "mcoi yxyp wgxg rzzj"

def decodificar_texto(texto_codificado):
    if not texto_codificado: return ""
    partes = decode_header(texto_codificado)
    texto_final = ""
    for texto, codificacion in partes:
        if isinstance(texto, bytes):
            texto_final += texto.decode(codificacion or "utf-8", errors="ignore")
        else:
            texto_final += texto
    return texto_final

def descargar_y_asignar_reportes():
    try:
        print("⏳ Conectando al correo de Gmail...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(CORREO_TALLER, PASSWORD_APP)
        mail.select("inbox")
        
        # 1. CAMBIO MAGISTRAL: Buscamos TODOS los correos (Leídos y No Leídos)
        status, mensajes = mail.search(None, "ALL")
        if status != "OK" or not mensajes[0]:
            print("✅ No hay correos.")
            return {"status": "info", "mensaje": "La bandeja de entrada está vacía."}
        
        # 2. Cogemos una base más amplia (los últimos 15 correos de la bandeja)
        id_lista = mensajes[0].split()[-15:] 
        print(f"📩 Revisando los últimos {len(id_lista)} correos del buzón. ¡Empezamos!")
        reportes_guardados = 0

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return {"status": "error", "mensaje": "Falta la clave de Google IA."}
            
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        for i, num in enumerate(id_lista, 1):
            print(f"\n🔍 [Correo {i}/{len(id_lista)}] Leyendo...")
            status, data = mail.fetch(num, "(RFC822)")
            
            for response_part in data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    asunto = decodificar_texto(msg.get("Subject"))
                    cuerpo = ""
                    
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ["text/plain", "text/html"]:
                                try:
                                    cuerpo += part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore") + "\n"
                                except: pass
                    else:
                        try:
                            cuerpo = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="ignore")
                        except: pass

                    texto_completo = f"ASUNTO: {asunto}\nCUERPO:\n{cuerpo}"
                    
                    print(f"   📧 Asunto: {asunto[:50]}...")
                    print("   🧠 Pensando...")

                    instruccion = """
                    Eres un experto leyendo correos de escáneres automotrices (como ThinkCar o Launch).
                    Extrae DOS cosas de este texto:
                    1. La MATRÍCULA del coche. Busca un código de 4 números y 3 letras (ej: 1234ABC o 9567HJR) o matrículas antiguas (ej: M1234AB). IGNORA los números de bastidor (VIN) de 17 caracteres, SOLO quiero la matrícula. Si no hay matrícula, devuelve NADA.
                    2. El enlace web (URL) para ver el reporte (suele empezar por http:// o https:// y terminar en un código largo).
                    
                    Responde EXACTAMENTE así:
                    CODIGO: [Matricula]
                    URL: [Enlace_web]
                    Si falta algo, pon NADA.
                    """
                    
                    respuesta_ia = model.generate_content(f"{instruccion}\n\nTEXTO:\n{texto_completo}").text.strip()
                    
                    codigo_vehiculo = ""
                    url_reporte = ""
                    for linea in respuesta_ia.split('\n'):
                        if "CODIGO:" in linea: codigo_vehiculo = linea.replace("CODIGO:", "").strip().upper()
                        if "URL:" in linea: url_reporte = linea.replace("URL:", "").strip()

                    print(f"   🤖 Código Detectado: {codigo_vehiculo}")
                    
                    if "NADA" in url_reporte or not url_reporte.startswith("http"):
                        print("   ❌ No se encontró ningún enlace al reporte. Saltando...")
                        continue

                    # 3. SISTEMA ANTI-DUPLICADOS (La joya de la corona)
                    if ReporteEscaner.objects.filter(enlace_web=url_reporte).exists():
                        print("   🔄 Este enlace ya está guardado en ServiMax. Saltando para no duplicar...")
                        continue

                    # 4. Asignamos a la Orden
                    if codigo_vehiculo and codigo_vehiculo != "NADA":
                        orden_activa = OrdenDeReparacion.objects.exclude(estado='Entregado').filter(
                            vehiculo__matricula__icontains=codigo_vehiculo
                        ).first()
                        
                        if orden_activa:
                            print(f"   🎯 ¡MATCH! Guardando enlace nuevo en la ficha de {orden_activa.vehiculo.matricula}.")
                            
                            ReporteEscaner.objects.create(
                                orden=orden_activa, 
                                enlace_web=url_reporte,
                                descripcion=f"Reporte Digital ({codigo_vehiculo})"
                            )
                            reportes_guardados += 1
                            
                        else:
                            print(f"   ⚠️ El coche '{codigo_vehiculo}' no está abierto en ServiMax.")
                            
        mail.logout()
        print("✅ Sincronización completada.")
        
        if reportes_guardados > 0:
            return {"status": "success", "mensaje": f"¡Éxito! J.A.R.V.I.S. ha archivado {reportes_guardados} reporte(s) nuevos."}
        else:
            return {"status": "info", "mensaje": "Se han revisado los últimos correos, pero no hay reportes nuevos pendientes para guardar."}
            
    except Exception as e:
        print(f"💥 ERROR CRÍTICO: {e}")
        return {"status": "error", "mensaje": f"Fallo al conectar con el correo: {str(e)}"}