#!/usr/bin/env python3
"""模块文档字符串
第二行
"""

import math   # 导入


def area(r):
    '''计算圆面积'''
    return math.pi * r * r


if __name__ == "__main__":
    print(area(1.0))  # 打印
