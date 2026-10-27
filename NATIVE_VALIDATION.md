# RCCAD Desktop 0.1 — weryfikacja wydania

- Kod aplikacji: `d26080aab98417e72da23367ca65d681f26357c7`.
- Proces Windows: https://github.com/czarny186-gif/RCCAD/actions/runs/40385478786
- Wydanie: https://github.com/czarny186-gif/RCCAD/releases/tag/desktop-v0.1.0-3
- Paczka: `RCCAD-Desktop-Windows-x64.zip`, 208142177 bajtów.
- SHA-256: `29589c27d5fa267ec7dcde139fc3ecd08a3f8822540a69e41acea9314ea2d3a7`.

## Wykonane sprawdzenia

32 testy silnika CAD, formatu projektu i działań natywnego interfejsu przeszły
na Linuksie oraz w procesie Windows. Na Linuksie dodatkowo uruchomiono rzeczywisty
widok OpenGL na Xvfb/Mesa: renderowanie, kliknięcie krawędzi w widoku i wykonanie
zaokrąglenia. Zrzut obejmował bryłę z otworem i zaokrąglonymi narożnikami.

Proces Windows zainstalował przypięte zależności, zbudował aplikację przez
PyInstaller i uruchomił gotowy `RCCAD Desktop.exe --self-test`.
Raport dołączony do paczki potwierdza platformę `Windows-2025Server-10.0.26100-SP0`
oraz powodzenie:

- zaokrąglenia 12 krawędzi i wspólnych narożników;
- otworu, odejmowania Boolean i wyciągnięcia szkicu;
- cofania/ponawiania, projektu RCCADX, STEP i STL;
- ładowania Qt, drzewa obiektów, właściwości oraz projekcji i promienia wyboru.

Po publikacji pobrano publiczny plik ZIP. Sprawdzono integralność całego archiwum,
obecność programu PE Windows x64 (`MZ`, `PE`, maszyna `0x8664`), katalogu bibliotek
`_internal` oraz pozytywnego raportu `selftest_windows.json`.

Windows 10/11 x64 jest platformą docelową. Proces budowania uruchamia aplikację
na Windows Server 2025 w trybie testowym bez rzeczywistego okna GPU; nie zastępuje
to testów sterownika graficznego na komputerze użytkownika. Wydanie 0.1 jest
wersją rozwojową, a nie pełną implementacją funkcji starszego programu HTML.
