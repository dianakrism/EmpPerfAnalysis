'''
Nama   : Dian Aprilia Krismonita
Tujuan : Kode ini dibuat untuk mengautomasi data mentah dari database PostgreSQL, membersihkan datanya, dan mengunggah ke Elasticsearch untuk keperluan analisis. Tools yang digunakan adalah Apache Airflow untuk memanage alurnya. Langkahnya meliputi ekstraksi data, cleaning dengan menangani duplikat dan kolom yang kosong (missing values), lalu mengindeks data ke Elasticsearch agar mempermudah akses.
'''

# Impor Modul
## Modul untuk manipulasi data
import pandas as pd
import os
## Modul untuk database adapter
import psycopg2 as db
## Handle keterangan waktu dan tanggal (timezone) di Elasticsearch
import pendulum
## Modul untuk menjadwalkan dan mengatur workflow di Apache Airflow
from airflow import DAG
from airflow.operators.python_operator import PythonOperator
## Modul untuk membuat koneksi dan berinteraksi dengan Elasticsearch
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

# Mengambil data dari PostgreSQL
def fetch_from_postgresql():
    '''
    Fungsi ini mengambil data dari PostgreSQL dan menyimpannya dalam file CSV.
    '''
    conn_string = "dbname='postgres' host='postgres' user='airflow' password='airflow'"
    conn = db.connect(conn_string)
    query = "SELECT * FROM table_m3;"

    # Ambil data dari PostgreSQL
    df = pd.read_sql(query, conn)
    conn.close()

    # Simpan data mentah ke file CSV
    df.to_csv('/opt/airflow/dags/raw_data.csv', index=False)
    print("Data berhasil diambil dari PostgreSQL dan disimpan dalam bentuk CSV.")

# Data Cleaning
def data_cleaning():
    '''
    Fungsi ini membersihkan data mentah dari file CSV.
    '''
    input_path = '/opt/airflow/dags/raw_data.csv'
    output_path = '/opt/airflow/dags/clean_data.csv'

    # Validasi keberadaan file
    if not os.path.exists(input_path):
        raise FileNotFoundError("File raw_data.csv tidak ditemukan di path yang ditentukan!")

    df = pd.read_csv('/opt/airflow/dags/raw_data.csv')

    # Validasi file kosong
    if df.empty:
        raise ValueError("File raw_data.csv kosong, tidak bisa melanjutkan proses cleaning!")

    # 1. Hapus entry yang terduplikat
    df = df.drop_duplicates()

    # 2. Handling missing values
    for column in df.columns:
        if df[column].dtype == 'float64' or df[column].dtype == 'int64':
            df[column].fillna(df[column].median(), inplace=True)
        else:
            df[column].fillna('Unknown', inplace=True)

    # 3. Menormalisasi nama kolom
    df.columns = df.columns.str.strip()  # Hapus spasi di awal/akhir
    df.columns = df.columns.str.lower()  # Ubah semua nama kolom jadi huruf kecil

    # 4. Format tanggal menjadi 'yyyy-mm-dd'
    if 'hire_date' in df.columns:
        df['hire_date'] = pd.to_datetime(df['hire_date']).dt.strftime('%Y-%m-%d')

    # Simpan data bersih ke file CSV
    df.to_csv('/opt/airflow/dags/clean_data.csv', index=False)
    print("Data telah dibersihkan dan disimpan dalam bentuk CSV.")

# Posting data bersih ke Elasticsearch
def post_to_elasticsearch():
    '''
    Fungsi ini mengunggah data bersih ke Elasticsearch.
    '''
    es = Elasticsearch([{'host': 'elasticsearch', 'port': 9200, 'scheme': 'http'}])

    # Validasi koneksi Elasticsearch
    if not es.ping():
        raise ValueError("Koneksi ke Elasticsearch gagal!")

    # Baca data bersih
    df = pd.read_csv('/opt/airflow/dags/clean_data.csv')

    # Siapkan data untuk diindeks
    actions = [
        {
            "_index": "emp_perf",  # Pastikan nama indeks sesuai
            "_source": r.dropna().to_dict()    # Tangani data kosong
        }
        for _, r in df.iterrows()
    ]

    # Bulk indexing
    try:
        bulk(es, actions, chunk_size=500)
        print(f"Berhasil mengindeks {len(actions)} dokumen ke Elasticsearch.")
    except Exception as e:
        print(f"Gagal selama bulk indexing: {str(e)}")

local_tz = pendulum.timezone("Asia/Jakarta")

# Konfigurasi DAG
default_args = {
    'owner': 'Dian',
    'start_date': local_tz.datetime(2024, 11, 1),
    'retries': 1
}

with DAG('m3_Dian',
         description='Automasi data dari PostgreSQL ke Elasticsearch',
         default_args=default_args,
         schedule_interval='10,20,30 9 * * 6',
         catchup=False
         ) as dag:

    fetch_data = PythonOperator(
        task_id='fetch_from_postgresql',
        python_callable=fetch_from_postgresql
    )

    clean_data = PythonOperator(
        task_id='data_cleaning',
        python_callable=data_cleaning
    )

    post_to_elastic = PythonOperator(
        task_id='post_to_elasticsearch',
        python_callable=post_to_elasticsearch
    )

    # Urutan tugas
    fetch_data >> clean_data >> post_to_elastic
