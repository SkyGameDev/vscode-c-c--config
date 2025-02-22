#include <iostream>
#include <conio.h>
#include <windows.h>
using namespace std;
const int width = 20;
const int height = 10;
int potatoX, potatoY;
int goalX, goalY;
bool gameOver;

void Setup() {
    gameOver = false;
    potatoX = width / 2;
    potatoY = height - 1;
    goalX = width - 2;
    goalY = 0;
}

void Draw() {
    system("cls"); // 清屏
    for (int i = 0; i < height; i++) {
        for (int j = 0; j < width; j++) {
            if (i == potatoY && j == potatoX)
                cout << "P"; // 土豆
            else if (i == goalY && j == goalX)
                std::cout << "G"; // 终点
            else if (i == height - 1)
                std::cout << "#"; // 地面
            else
                std::cout << " ";
        }
        std::cout << std::endl;
    }
}

void Input() {
    if (_kbhit()) {
        char key = _getch();
        if (key == 'a' && potatoX > 0)
            potatoX--;
        else if (key == 'd' && potatoX < width - 1)
            potatoX++;
        else if (key == 'w' && potatoY > 0)
            potatoY--;
        else if (key == 's' && potatoY < height - 1)
            potatoY++;
        else if (key == 'q')
            gameOver = true;
    }
}

void Logic() {
    if (potatoX == goalX && potatoY == goalY) {
        gameOver = true;
        std::cout << "You Win!" << std::endl;
    }
}

int main() {
    Setup();
    while (!gameOver) {
        Draw();
        Input();
        Logic();
        Sleep(100); // 控制游戏速度
    }
    return 0;
}