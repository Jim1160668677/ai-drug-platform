.PHONY: help up down dev build logs ps migrate seed test lint clean

help: ## 显示帮助
	@echo "精准药物设计系统 - 快捷命令"
	@echo ""
	@echo "使用方法: make <target>"
	@echo ""
	@echo "常用命令:"
	@echo "  up        启动所有服务（后台）"
	@echo "  down      停止所有服务"
	@echo "  dev       启动开发模式（前台+热重载）"
	@echo "  build     构建所有镜像"
	@echo "  logs      查看所有服务日志"
	@echo "  ps        查看服务状态"
	@echo "  migrate   执行数据库迁移"
	@echo "  seed      灌入样本数据"
	@echo "  test      运行后端测试"
	@echo "  lint      代码检查"
	@echo "  clean     清理容器和卷"

# Docker Compose 基础命令
COMPOSE := docker compose -f docker/docker-compose.yml --env-file .env

up: ## 启动所有服务
	$(COMPOSE) up -d
	@echo ""
	@echo "✓ 服务启动中..."
	@echo "  前端: http://localhost"
	@echo "  API 文档: http://localhost/docs"
	@echo "  MinIO 控制台: http://localhost:9001"
	@echo "  Neo4j: http://localhost:7474"

down: ## 停止所有服务
	$(COMPOSE) down

dev: ## 开发模式（显示日志）
	$(COMPOSE) up

build: ## 构建镜像
	$(COMPOSE) build

logs: ## 查看日志
	$(COMPOSE) logs -f --tail=100

ps: ## 服务状态
	$(COMPOSE) ps

# 数据库命令
migrate: ## 执行数据库迁移
	$(COMPOSE) exec backend alembic upgrade head
	@echo "✓ 数据库迁移完成"

seed: ## 灌入样本数据
	$(COMPOSE) exec backend python -m app.db.seed
	@echo "✓ 样本数据已灌入"

migrate-new: ## 创建新迁移 (make migrate-new m="add xxx")
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(m)"

# 开发命令
test: ## 运行测试
	$(COMPOSE) exec backend pytest -v

lint: ## 代码检查
	$(COMPOSE) exec backend ruff check app/
	$(COMPOSE) exec frontend npm run lint

shell-backend: ## 进入后端容器
	$(COMPOSE) exec backend /bin/bash

shell-frontend: ## 进入前端容器
	$(COMPOSE) exec frontend sh

shell-db: ## 进入数据库
	$(COMPOSE) exec postgres psql -U pdd -d precision_drug

# 第三阶段服务
up-phase3: ## 启动联邦学习服务
	$(COMPOSE) --profile phase3 up -d

clean: ## 清理所有容器和卷（危险！）
	@echo "警告：将删除所有数据！按 Ctrl+C 取消，5秒后继续..."
	@sleep 5
	$(COMPOSE) down -v
	@echo "✓ 已清理"

# 单独服务
backend-only: ## 仅启动基础设施+后端
	$(COMPOSE) up -d postgres redis chromadb neo4j minio backend worker

frontend-only: ## 仅启动前端
	$(COMPOSE) up -d frontend
