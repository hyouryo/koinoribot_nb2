"""
颜色转换工具

用于将 LAB 颜色空间转换为 RGB
"""

try:
    from skimage import color
    import numpy as np
    
    def lab2rgb(lightness: float, a: float, b: float) -> tuple:
        """将 LAB 颜色转换为 RGB"""
        lab = np.array([lightness, a, b], dtype=float)
        value = list(color.lab2rgb(lab))
        red = int(value[0] * 255)
        green = int(value[1] * 255)
        blue = int(value[2] * 255)
        return (red, green, blue)
except ImportError:
    # 如果没有安装 skimage，使用简化的转换
    def lab2rgb(lightness: float, a: float, b: float) -> tuple:
        """简化的 LAB 到 RGB 转换"""
        # 简单的线性映射作为后备
        r = int(max(0, min(255, lightness * 2.55 + a)))
        g = int(max(0, min(255, lightness * 2.55 - a)))
        b = int(max(0, min(255, lightness * 2.55 + b)))
        return (r, g, b)
