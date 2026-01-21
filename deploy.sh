#!/bin/bash
# AI Purchase Agent - Deploy Script for Ubuntu 24.04
# Использование: curl -sSL https://raw.githubusercontent.com/YOUR_REPO/deploy.sh | bash
# Или: chmod +x deploy.sh && ./deploy.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    log_error "Please do not run as root. Script will use sudo when needed."
    exit 1
fi

echo "========================================"
echo "  AI Purchase Agent - Deploy Script"
echo "  Ubuntu 24.04 LTS"
echo "========================================"
echo ""

# Configuration
REPO_URL="${REPO_URL:-https://github.com/YOUR_USERNAME/ai-purchase-agent.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/ai-purchase-agent}"
BRANCH="${BRANCH:-master}"

# Step 1: Update system
log_info "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Step 2: Install Docker
log_info "Installing Docker..."

if ! command -v docker &> /dev/null; then
    # Remove old versions
    sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

    # Install prerequisites
    sudo apt-get install -y \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg \
        lsb-release

    # Add Docker GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    # Add Docker repository
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Add current user to docker group
    sudo usermod -aG docker $USER
    log_info "Docker installed successfully"
    log_warn "You may need to log out and back in for docker group membership to take effect"
else
    log_info "Docker is already installed"
fi

# Step 3: Install Docker Compose (standalone, for compatibility)
log_info "Checking Docker Compose..."

if ! command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep -oP '"tag_name": "\K(.*)(?=")')
    sudo curl -L "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    log_info "Docker Compose installed: $COMPOSE_VERSION"
else
    log_info "Docker Compose is already installed"
fi

# Step 4: Clone or update repository
log_info "Setting up project..."

if [ -d "$INSTALL_DIR" ]; then
    log_info "Project directory exists, pulling latest changes..."
    cd "$INSTALL_DIR"
    git fetch origin
    git checkout $BRANCH
    git pull origin $BRANCH
else
    log_info "Cloning repository..."
    git clone -b $BRANCH "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Step 5: Create data directories
log_info "Creating data directories..."
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/cookies_backup"

# Step 6: Setup environment file
if [ ! -f "$INSTALL_DIR/.env" ]; then
    log_info "Creating .env file from template..."
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    log_warn "Please edit .env file with your credentials:"
    log_warn "  nano $INSTALL_DIR/.env"
    echo ""
    echo "Required settings in .env:"
    echo "  - STPARTS_LOGIN: Your STparts.ru login"
    echo "  - STPARTS_PASSWORD: Your STparts.ru password"
    echo ""
else
    log_info ".env file already exists"
fi

# Step 7: Initialize database
log_info "Initializing database..."
if [ ! -f "$INSTALL_DIR/data/tasks.db" ]; then
    # Create empty database with schema
    cat > /tmp/init_db.py << 'EOF'
import sqlite3
import sys

db_path = sys.argv[1] if len(sys.argv) > 1 else "tasks.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        partnumber TEXT NOT NULL,
        search_brand TEXT,
        status TEXT NOT NULL DEFAULT 'PENDING',
        min_price REAL,
        avg_price REAL,
        zzap_min_price REAL,
        stparts_min_price REAL,
        trast_min_price REAL,
        autovid_min_price REAL,
        autotrade_min_price REAL,
        brand TEXT,
        result_url TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP
    )
""")

# Add new columns if they don't exist (migration for existing databases)
for column in ['trast_min_price', 'autovid_min_price', 'autotrade_min_price']:
    try:
        cursor.execute(f"ALTER TABLE tasks ADD COLUMN {column} REAL")
    except sqlite3.OperationalError:
        pass  # Column already exists

conn.commit()
conn.close()
print(f"Database initialized: {db_path}")
EOF
    python3 /tmp/init_db.py "$INSTALL_DIR/data/tasks.db"
    rm /tmp/init_db.py
fi

# Step 8: Build Docker images
log_info "Building Docker images..."
cd "$INSTALL_DIR"

# Use docker compose (plugin) or docker-compose (standalone)
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

$COMPOSE_CMD build

# Step 9: Start services
log_info "Starting services..."
$COMPOSE_CMD up -d

# Wait for services to start
log_info "Waiting for services to start..."
sleep 10

# Step 10: Check status
log_info "Checking service status..."
$COMPOSE_CMD ps

# Get server IP
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "========================================"
echo "  Deployment Complete!"
echo "========================================"
echo ""
echo "Web interface: http://${SERVER_IP}:8000"
echo "API endpoint:  http://${SERVER_IP}:8000/api/tasks"
echo ""
echo "Useful commands:"
echo "  cd $INSTALL_DIR"
echo "  $COMPOSE_CMD logs -f          # View logs"
echo "  $COMPOSE_CMD logs -f worker   # View worker logs"
echo "  $COMPOSE_CMD restart          # Restart services"
echo "  $COMPOSE_CMD down             # Stop services"
echo "  $COMPOSE_CMD up -d            # Start services"
echo ""

# Check if .env needs configuration
if grep -q "your_email@example.com" "$INSTALL_DIR/.env" 2>/dev/null; then
    log_warn "Don't forget to configure .env with your STparts.ru credentials!"
    log_warn "  nano $INSTALL_DIR/.env"
    log_warn "Then restart: $COMPOSE_CMD restart"
fi
