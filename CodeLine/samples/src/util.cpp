// util.cpp -- 演示文件
#include "util.hpp"

/*
 * 计算阶乘
 * 迭代实现
 */
long long factorial(int n)
{
    long long r = 1;
    for (int i = 2; i <= n; ++i)   // 从 2 开始累乘
        r *= i;
    return r;
}

/* 判断偶数 */
bool isEven(int n) { return n % 2 == 0; }
