from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import time
from insert_data import fetch_data_from_api, insert_data
from database import create_db_connection, fetch_cnpj_list, fetch_existing_cnpjs
from config import load_env, get_db_params
from tqdm import tqdm

app = Flask(__name__)
socketio = SocketIO(app)
process_thread = None
stop_event = threading.Event()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start():
    global process_thread, stop_event
    if process_thread is None or not process_thread.is_alive():
        stop_event.clear()
        process_thread = threading.Thread(target=process_cnpjs)
        process_thread.start()
        return jsonify({'status': 'started'})
    else:
        stop_event.set()
        process_thread.join()
        return jsonify({'status': 'stopped'})

def process_cnpjs():
    load_env()
    db_params = get_db_params()
    cnpj_list = fetch_cnpj_list(db_params)
    conn = create_db_connection()
    total_cnpjs_sitac = len(cnpj_list)
    total_cnpjs_final = len(fetch_existing_cnpjs(conn))
    consulted_cnpjs = 0
    session_consulted = 0

    with tqdm(total=total_cnpjs_sitac, desc="Inserindo CNPJs", unit="CNPJ") as pbar:
        for cnpj in cnpj_list:
            if stop_event.is_set():
                socketio.emit('status', {'message': 'Processo parado'})
                break

            cnpj_code = cnpj[0]
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM empresa WHERE cnpj = %s", (cnpj_code,))
                if cur.fetchone():
                    socketio.emit('log', {'message': f"CNPJ {cnpj_code} já existe no banco de dados. Pulando..."})
                    pbar.update(1)
                    consulted_cnpjs += 1
                    socketio.emit('progress', {
                        'consulted': consulted_cnpjs,
                        'total': total_cnpjs_sitac,
                        'session_consulted': session_consulted,
                        'total_sitac': total_cnpjs_sitac,
                        'total_final': total_cnpjs_final
                    })
                    continue

            data = fetch_data_from_api(cnpj_code)
            if data:
                insert_data(conn, data)
                time.sleep(20)
            pbar.update(1)
            consulted_cnpjs += 1
            session_consulted += 1
            total_cnpjs_final += 1 
            socketio.emit('progress', {
                'consulted': consulted_cnpjs,
                'total': total_cnpjs_sitac,
                'session_consulted': session_consulted,
                'total_sitac': total_cnpjs_sitac,
                'total_final': total_cnpjs_final
            })
            socketio.emit('log', {'message': f"CNPJ {cnpj_code} inserido com sucesso."})

    conn.close()
    socketio.emit('status', {'message': 'Processo concluído'})

if __name__ == '__main__':
    socketio.run(app, debug=True)