import os
import sys
import discord
from discord.ext import commands
import psycopg2
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# --- CONFIGURAÇÕES ---
def carregar_config():
    load_dotenv(override=True)
    if not os.getenv('DISCORD_TOKEN'):
        diretorio_script = os.path.dirname(os.path.abspath(__file__))
        caminho_env = os.path.join(diretorio_script, '.env')
        if os.path.exists(caminho_env):
            with open(caminho_env, "r", encoding="utf-8") as f:
                for linha in f:
                    if "=" in linha and not linha.startswith("#"):
                        k, v = linha.split("=", 1)
                        os.environ[k.strip()] = v.strip().replace('"', '').replace("'", "")

carregar_config()

TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
# IDs ou nomes dos canais permitidos
CANAIS_PERMITIDOS = [1434310955004592360, 1412423356946317350]

if not TOKEN:
    print("❌ ERRO: DISCORD_TOKEN não encontrado!")
    sys.exit(1)

# --- CONFIGURAÇÃO DO BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- BANCO DE DADOS ---
def get_db_connection():
    if not DATABASE_URL: return None
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
    try: return psycopg2.connect(url, sslmode='require', connect_timeout=10)
    except: return None

def setup_db():
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (id BIGINT PRIMARY KEY, rep INTEGER DEFAULT 0, ultima_rep TIMESTAMP)''')
        conn.commit()
        cursor.close()
        conn.close()

def alterar_rep(user_id, quantidade, definir=False):
    conn = get_db_connection()
    if not conn: return 0
    cursor = conn.cursor()
    if definir:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    else:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = usuarios.rep + EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    res = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return res[0] if res else 0

# --- SISTEMA DE LOGS ---
async def enviar_log(ctx, mensagem, cor=0xffa500):
    if LOG_CHANNEL_ID == 0: return
    canal = bot.get_channel(LOG_CHANNEL_ID)
    if canal:
        embed = discord.Embed(title="🛰️ Registro de Atividade", description=mensagem, color=cor, timestamp=datetime.now())
        embed.set_footer(text=f"Executor: {ctx.author.name}")
        await canal.send(embed=embed)

# --- CHECKS (VERIFICAÇÕES) ---

@bot.check
async def verificar_canal(ctx):
    if isinstance(ctx.channel, discord.DMChannel): 
        return False
    
    # IDs das suas configurações
    ID_FORUM_TROCA = 1434310955004592360
    ID_CANAL_STAFF = 1412423356946317350

    # Verificações de Identidade
    is_admin = ctx.author.guild_permissions.administrator
    is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
    
    # Identificar se o canal atual é uma Thread (Post de Fórum)
    # Se for thread, o parent_id é o ID do Canal de Fórum
    parent_id = getattr(ctx.channel, "parent_id", None)
    
    no_forum_troca = (ctx.channel.id == ID_FORUM_TROCA or parent_id == ID_FORUM_TROCA)
    no_canal_staff = (ctx.channel.id == ID_CANAL_STAFF or parent_id == ID_CANAL_STAFF)

    # REGRA:
    # 1. Staff (Admin/Mod) pode usar no Fórum (em tópicos ou na raiz) e no canal de Staff
    if is_admin or is_mod:
        return no_forum_troca or no_canal_staff
    
    # 2. Membros Comuns: Só podem usar se estiverem DENTRO de um tópico do Fórum de Trocas
    return no_forum_troca

# 2. Check de Staff
def eh_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin: return True
        await ctx.send("❌ Você não tem permissão para usar este comando.", delete_after=5)
        return False
    return commands.check(predicate)

# 3. Check para ignorar cooldown
def ignora_cooldown_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin:
            ctx.command.reset_cooldown(ctx)
        return True
    return commands.check(predicate)

# --- SISTEMA DE CARGOS ---
async def verificar_cargos_nivel(ctx, membro, pontos):
    niveis = [{"limite": 100, "nome": "trocador oficial"}, {"limite": 50, "nome": "trocador confiavel"}, {"limite": 10, "nome": "trocador iniciante"}]
    cargo_perigoso = discord.utils.get(ctx.guild.roles, name="trocador perigoso")
    if pontos <= -10 and cargo_perigoso:
        if cargo_perigoso not in membro.roles: await membro.add_roles(cargo_perigoso)
    elif cargo_perigoso and cargo_perigoso in membro.roles and pontos > -10:
        await membro.remove_roles(cargo_perigoso)
    for nivel in niveis:
        cargo = discord.utils.get(ctx.guild.roles, name=nivel["nome"])
        if cargo:
            if pontos >= nivel["limite"] and cargo not in membro.roles: await membro.add_roles(cargo)
            elif pontos < nivel["limite"] and cargo in membro.roles: await membro.remove_roles(cargo)

# --- EVENTOS ---
@bot.event
async def on_ready():
    setup_db()
    print(f'✅ {bot.user.name} está ONLINE!')
    await bot.change_presence(activity=discord.Game(name="!ajuda | ARC Raiders Brasil"))

# --- COMANDOS ---
@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Central de Comandos", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação.", inline=True)
    embed.add_field(name="💢 `!neg @membro`", value="Dá -1 de reputação.", inline=True)
    embed.add_field(name="👤 `!perfil @membro`", value="Ver reputação.", inline=True)
    embed.add_field(name="🏆 `!top`", value="Ver o ranking dos 10 melhores.", inline=True) # <-- Linha nova
    
    if any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator:
        embed.add_field(name="🛠️ Staff", value="`!setrep`, `!resetar`, `!restart`, `!say`", inline=False)
    
    embed.set_footer(text="Desenvolvido por fugazzeto para ARC Raiders Brasil.")
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    if not conn:
        return await ctx.send("❌ Erro ao conectar ao banco de dados.")
    
    cursor = conn.cursor()
    # Limitamos a busca aos 10 melhores
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    usuarios = cursor.fetchall()
    cursor.close()
    conn.close()

    if not usuarios:
        return await ctx.send("⚠️ O ranking ainda está vazio.")

    descricao = ""
    for i, (uid, pontos) in enumerate(usuarios, 1):
        # Tenta buscar o nome do usuário
        user = bot.get_user(uid)
        nome = user.name if user else f"Usuário Antigo ({uid})"
        
        # Formatação visual do ranking
        if i == 1:
            prefixo = "🥇 "
        elif i == 2:
            prefixo = "🥈 "
        elif i == 3:
            prefixo = "🥉 "
        else:
            prefixo = f"**{i}.** "

        descricao += f"{prefixo}{nome} — `{pontos} pts` \n"

    embed = discord.Embed(
        title="🏆 Top 10 - Maiores Reputações",
        description=descricao,
        color=0xf1c40f, # Cor dourada
        timestamp=datetime.now()
    )
    embed.set_footer(text="ARC Raiders Brasil | Ranking de Confiança")
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 7200, commands.BucketType.user)
@ignora_cooldown_staff()
async def rep(ctx, membro: discord.Member):
    if membro.id == ctx.author.id or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Você não pode dar reputação para si mesmo ou bots.")
    nova = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu +1 rep para {membro.mention}!")
    await enviar_log(ctx, f"🌟 **Reputação Positiva**\nPara: {membro.mention}\nTotal: `{nova}`", 0x2ecc71)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@commands.cooldown(1, 7200, commands.BucketType.user)
@ignora_cooldown_staff()
async def neg(ctx, membro: discord.Member):
    if membro.id == ctx.author.id or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Alvo inválido.")
    nova = alterar_rep(membro.id, -1)
    await ctx.send(f"💢 {ctx.author.mention} deu -1 rep para {membro.mention}!")
    await enviar_log(ctx, f"💢 **Reputação Negativa**\nPara: {membro.mention}\nTotal: `{nova}`", 0xe74c3c)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
async def perfil(ctx, membro: discord.Member = None):
    membro = membro or ctx.author
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res = cursor.fetchone()
    pontos = res[0] if res else 0
    conn.close()
    status = "Neutro"
    if pontos >= 100: status = "Trocador Oficial 💎"
    elif pontos >= 50: status = "Trocador Confiável ✅"
    elif pontos >= 10: status = "Trocador Iniciante ✅"
    elif pontos <= -10: status = "Trocador Perigoso ❌"
    embed = discord.Embed(title=f"Perfil de {membro.name}", color=discord.Color.gold())
    embed.add_field(name="Pontos", value=f"`{pontos}`", inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.set_thumbnail(url=membro.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
@eh_staff()
async def setrep(ctx, membro: discord.Member, valor: int):
    nova = alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Rep de {membro.mention} definida para `{valor}`.")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        minutos = int(error.retry_after // 60)
        await ctx.send(f"⏳ Aguarde {minutos} minutos.", delete_after=10)
    elif isinstance(error, commands.CheckFailure):
        # Opcional: Avisar que o canal está errado
        if not ctx.author.guild_permissions.administrator:
             await ctx.send(f"❌ {ctx.author.mention}, este comando não pode ser usado aqui.", delete_after=7)

if __name__ == "__main__":
    setup_db()
    bot.run(TOKEN)