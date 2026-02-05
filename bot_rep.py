import discord
from discord.ext import commands
import os
import psycopg2
from dotenv import load_dotenv
from datetime import timedelta
import sys

# --- CARREGAMENTO DE CONFIGURAÇÕES ---
def carregar_config():
    load_dotenv(override=True)
    diretorio_script = os.path.dirname(os.path.abspath(__file__))
    caminho_env = os.path.join(diretorio_script, '.env')
    
    if os.path.exists(caminho_env):
        with open(caminho_env, "r", encoding="utf-8", errors="ignore") as f:
            for linha in f:
                linha = linha.strip()
                if linha and "=" in linha and not linha.startswith("#"):
                    chave, valor = linha.split("=", 1)
                    os.environ[chave.strip()] = valor.strip().replace('"', '').replace("'", "")

carregar_config()

TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 1433136439456956576))

if not TOKEN:
    print("❌ ERRO: DISCORD_TOKEN não encontrado!")
    sys.exit()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# --- BANCO DE DADOS POSTGRESQL ---

def get_db_connection():
    url = os.getenv('DATABASE_URL')
    if not url: return None
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    try:
        return psycopg2.connect(url, sslmode='require', connect_timeout=5)
    except:
        try:
            return psycopg2.connect(url, sslmode='disable', connect_timeout=5)
        except Exception as e:
            print(f"❌ Erro banco: {e}")
            return None

def setup_db():
    conn = get_db_connection()
    if conn is None: return
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id BIGINT PRIMARY KEY,
            rep INTEGER DEFAULT 0,
            ultima_rep TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

def alterar_rep(user_id, quantidade, definir=False):
    conn = get_db_connection()
    if conn is None: return 0
    cursor = conn.cursor()
    if definir:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    else:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = usuarios.rep + EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    nova_pontuacao = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return nova_pontuacao

# --- FUNÇÕES DE VERIFICAÇÃO ---

def eh_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin:
            return True
        await ctx.send("❌ Você não tem permissão (**mods** ou **admin**) para usar este comando.")
        return False
    return commands.check(predicate)

async def verificar_cargos_nivel(ctx, membro, pontos):
    niveis = [
        {"limite": 100, "nome": "trocador oficial"},
        {"limite": 50, "nome": "trocador confiavel"},
        {"limite": 10, "nome": "trocador iniciante"}
    ]
    
    cargo_perigoso_nome = "trocador perigoso"
    cargo_perigoso = discord.utils.get(ctx.guild.roles, name=cargo_perigoso_nome)

    if pontos <= -10:
        if cargo_perigoso and cargo_perigoso not in membro.roles:
            try:
                await membro.add_roles(cargo_perigoso)
                await ctx.send(f"⚠️ **ATENÇÃO:** {membro.mention} atingiu reputação crítica e recebeu o cargo **{cargo_perigoso_nome}**! 💀")
            except: pass
    else:
        if cargo_perigoso and cargo_perigoso in membro.roles:
            try:
                await membro.remove_roles(cargo_perigoso)
                await ctx.send(f"✅ {membro.mention} não possui mais reputação crítica. Cargo **{cargo_perigoso_nome}** removido.")
            except: pass

    for nivel in niveis:
        cargo = discord.utils.get(ctx.guild.roles, name=nivel["nome"])
        if cargo:
            if pontos < nivel["limite"] and cargo in membro.roles:
                try: await membro.remove_roles(cargo)
                except: pass
            elif pontos >= nivel["limite"] and cargo not in membro.roles:
                try:
                    await membro.add_roles(cargo)
                    await ctx.send(f"🎉 **{membro.display_name}** subiu para **{cargo.name}**!")
                except: pass
                break

# --- EVENTOS ---

@bot.event
async def on_ready():
    setup_db()
    print(f'✅ {bot.user.name} está ONLINE!')
    await bot.change_presence(activity=discord.Game(name="Digite: !ajuda"))

    # VERIFICAÇÃO DE RESTART: Avisa no canal se o bot foi reiniciado por comando
    if len(sys.argv) > 1:
        try:
            channel_id = int(sys.argv[-1])
            channel = bot.get_channel(channel_id)
            if channel:
                await channel.send("✅ **Bot online!** O processo de reinicialização foi concluído.")
            
            # Remove o argumento para evitar loops de mensagem em crash
            sys.argv.pop()
        except Exception:
            pass

# --- COMANDOS ---

@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Bot de Reputação - ARC Raiders Brasil", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação (1 uso/hora).", inline=False)
    embed.add_field(name="💢 `!neg @membro`", value="Dá -1 de reputação (1 uso/hora).", inline=False)
    embed.add_field(name="👤 `!perfil @membro`", value="Ver reputação e medalha de alguém.", inline=False)
    embed.add_field(name="🏆 `!top`", value="Ranking dos 10 melhores trocadores.", inline=False)
    
    # Verifica se é staff para mostrar comandos extras
    is_staff = any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator
    if is_staff:
        embed.add_field(name="🛠️ Staff", value="`!setrep`, `!resetar`, `!restart`, `!say`", inline=False)
    
    embed.set_footer(text="Desenvolvido por fugazzeto para ARC Raiders Brasil.")
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user)
async def rep(ctx, membro: discord.Member):
    if membro == ctx.author or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Alvo inválido.")
    nova = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu **+1** de rep para {membro.mention}!")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def neg(ctx, membro: discord.Member):
    nova = alterar_rep(membro.id, -1)
    await ctx.send(f"💢 {ctx.author.mention} deu **-1** de rep para {membro.mention}!")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
async def perfil(ctx, membro: discord.Member = None):
    membro = membro or ctx.author
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res = cursor.fetchone()
    pontos = res[0] if res else 0
    cursor.close()
    conn.close()
    
    med = "👍"
    if pontos >= 100: med = "🥇"
    elif pontos >= 50: med = "🥈"
    elif pontos >= 10: med = "🥉"
    elif pontos <= -10: med = "💀"
    elif pontos < 0: med = "⚠️"
    await ctx.send(f"👤 {membro.mention} | Status: {med} **{pontos}** pontos.")

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    lb = cursor.fetchall()
    cursor.close()
    conn.close()
    msg = "🏆 **RANKING DE REPUTAÇÃO**\n" + "\n".join([f"`{i}.` <@{uid}> - **{r}**" for i, (uid, r) in enumerate(lb, 1)])
    await ctx.send(msg)

# --- COMANDOS DE STAFF (CONTROLE) ---

@bot.command()
@eh_staff()
async def setrep(ctx, membro: discord.Member, valor: int):
    nova = alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Reputação de {membro.mention} definida para `{valor}`.")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def resetar(ctx, membro: discord.Member):
    alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"⚠️ Reputação de {membro.mention} resetada.")

@bot.command()
@eh_staff()
async def restart(ctx):
    """Reinicia o bot e passa o ID do canal atual como argumento"""
    await ctx.send("🔄 O bot está sendo reiniciado e estará online em poucos segundos.")
    # Inicia um novo processo do python com o canal atual como argumento extra
    os.execv(sys.executable, [sys.executable, __file__, str(ctx.channel.id)])

@bot.command()
@eh_staff()
async def say(ctx, *, mensagem: str):
    """Faz o bot repetir uma mensagem (Apenas Mods e Admin)"""
    try:
        # Tenta deletar a mensagem do usuário para o comando ficar 'invisível'
        await ctx.message.delete()
    except:
        # Caso o bot não tenha permissão de gerenciar mensagens, ele ignora o erro
        pass
    
    # Envia a mensagem digitada
    await ctx.send(mensagem)

# --- TRATAMENTO DE ERROS ---

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Aguarde {int(error.retry_after)}s.")
    elif isinstance(error, commands.CheckFailure):
        pass

bot.run(TOKEN)