import discord
from discord.ext import commands
import os
import psycopg2
from dotenv import load_dotenv
from datetime import timedelta

# Carrega variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Configuração de Intenções
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# --- BANCO DE DADOS POSTGRESQL ---
def get_db_connection():
    url = os.getenv('DATABASE_URL')
    if not url:
        print("❌ ERRO: A variável DATABASE_URL não foi encontrada!")
        return None

    # Ajuste de prefixo para compatibilidade com SQLAlchemy/Psycopg2
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        
    return psycopg2.connect(url, sslmode='require')

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

def alterar_rep(user_id, quantidade):
    conn = get_db_connection()
    if conn is None: return 0
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO usuarios (id, rep) VALUES (%s, %s)
        ON CONFLICT (id) DO UPDATE SET rep = usuarios.rep + EXCLUDED.rep
        RETURNING rep
    ''', (user_id, quantidade))
    nova_pontuacao = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return nova_pontuacao

# --- EVENTOS ---
@bot.event
async def on_ready():
    setup_db()
    print(f'✅ {bot.user.name} está online com PostgreSQL!')
    await bot.change_presence(activity=discord.Game(name="Digite: !ajuda"))

# --- COMANDOS PÚBLICOS ---

@bot.command()
async def ajuda(ctx):
    """Comando de Ajuda"""
    embed = discord.Embed(
        title="📖 Guia de Comandos - ARC Raiders Brasil",
        description="Use os comandos abaixo para gerenciar sua reputação.",
        color=discord.Color.blue()
    )
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 ponto de reputação (1 uso por hora).", inline=False)
    embed.add_field(name="👤 `!perfil @membro`", value="Vê a reputação atual.", inline=False)
    embed.add_field(name="🏆 `!top`", value="Ranking dos 10 melhores.", inline=False)
    
    if ctx.author.guild_permissions.manage_messages:
        embed.add_field(name="🛠️ Moderação", value="`!setrep @membro [valor]`\n`!resetar @membro`", inline=False)
    
    embed.set_footer(text="Sistema de Reputação Ativo")
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user)
async def rep(ctx, membro: discord.Member):
    if membro == ctx.author:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Você não pode dar reputação a si mesmo!")
    
    nova_pontuacao = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu +1 de reputação para {membro.mention}!")

    if nova_pontuacao >= 100:
        cargo = discord.utils.get(ctx.guild.roles, name="trocador oficial")
        if cargo and cargo not in membro.roles:
            try:
                await membro.add_roles(cargo)
                await ctx.send(f"🎉 {membro.mention} atingiu **100 pontos** e ganhou o cargo **{cargo.name}**!")
            except:
                pass

@bot.command()
async def perfil(ctx, membro: discord.Member = None):
    membro = membro or ctx.author
    conn = get_db_connection()
    if conn is None: return
    cursor = conn.cursor()
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res = cursor.fetchone()
    pontos = res[0] if res else 0
    cursor.close()
    conn.close()
    
    embed = discord.Embed(title=f"Perfil de {membro.display_name}", color=discord.Color.green())
    embed.add_field(name="Reputação Atual", value=f"✨ `{pontos}` pontos")
    embed.set_thumbnail(url=membro.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    if conn is None: return
    cursor = conn.cursor()
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    leaderboard = cursor.fetchall()
    cursor.close()
    conn.close()

    if not leaderboard:
        return await ctx.send("O ranking ainda está vazio!")

    embed = discord.Embed(title="🏆 Melhores Trocadores", color=discord.Color.gold())
    descricao = ""
    for i, (user_id, pontos) in enumerate(leaderboard, 1):
        user = bot.get_user(user_id)
        nome = user.name if user else f"ID:{user_id}"
        descricao += f"`#{i:02d}` **{nome}** — {pontos} reps\n"
            
    embed.description = descricao
    await ctx.send(embed=embed)

# --- TRATAMENTO DE ERROS ---
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        tempo = str(timedelta(seconds=int(error.retry_after)))
        await ctx.send(f"⏳ Calma! Você pode dar rep novamente em `{tempo}`.")
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        print(f"Erro: {error}")

bot.run(TOKEN)