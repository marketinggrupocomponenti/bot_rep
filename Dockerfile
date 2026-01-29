FROM python:3.11-slim

# Instala dependências para o PostgreSQL
RUN apt-get update && apt-get install -y libpq-dev gcc

# Define a pasta de trabalho
WORKDIR /app

# Copia os arquivos de requisitos primeiro (otimiza o cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia TODO o conteúdo da sua pasta para dentro do container
COPY . .

# Comando para rodar o bot (sem o caminho /app/, pois já estamos dentro dele)
CMD ["python", "bot_rep.py"]