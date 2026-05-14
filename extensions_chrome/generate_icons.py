#!/usr/bin/env python3
"""
Script para gerar ícones da extensão Chrome
Cria PNG simples com um ícone de câmera/microfone
"""

from PIL import Image, ImageDraw
import os

def create_icon(size):
    """Cria um ícone PNG com o tamanho especificado"""
    # Cria imagem com fundo azul escuro (tema da extensão)
    img = Image.new('RGB', (size, size), color='#16213e')
    draw = ImageDraw.Draw(img)
    
    # Desenha um círculo branco (representando câmera/microfone)
    margin = size // 6
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill='#ffffff',
        outline='#4caf8a',
        width=2
    )
    
    # Desenha um círculo dentro (efeito de câmera)
    inner_margin = size // 3
    draw.ellipse(
        [inner_margin, inner_margin, size - inner_margin, size - inner_margin],
        fill='#16213e',
        outline='#4caf8a',
        width=1
    )
    
    return img

# Cria a pasta icons se não existir
icons_dir = os.path.join(os.path.dirname(__file__), 'icons')
os.makedirs(icons_dir, exist_ok=True)

# Gera ícones nos tamanhos requeridos
sizes = [16, 48, 128]
for size in sizes:
    icon = create_icon(size)
    output_path = os.path.join(icons_dir, f'icon{size}.png')
    icon.save(output_path)
    print(f"✓ Criado: {output_path}")

print("\n✅ Todos os ícones foram gerados com sucesso!")
