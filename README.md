# Perforacja DXF

Perforacja DXF to aplikacja okienkowa do rozmieszczania otworów w płaskim
detalu opisanym konturami z pliku DXF. Program pokazuje rysunek źródłowy i
podgląd perforacji, a wynik zapisuje jako nowy plik DXF.

Interfejs został zbudowany w PyQt5. Kod aplikacji jest przeznaczony dla
Windows i Linux; gotowy plik EXE można zbudować w Windows.

## Wymagania

- Python 3.10 lub nowszy.
- Plik wejściowy DXF z zamkniętymi konturami detalu.
- Biblioteki wymienione w `requirements.txt` (instalowane w instrukcjach
  poniżej).

## Uruchamianie w Windows

Otwórz PowerShell w folderze projektu i wykonaj:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Jeśli polecenie `py` nie jest dostępne, użyj `python` do utworzenia
środowiska:

```powershell
python -m venv .venv
```

Przy zablokowanej aktywacji środowiska można wywołać jego interpreter
bez aktywowania:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## Uruchamianie w Linux

W Debianie i Ubuntu najpierw zainstaluj Pythona, moduł venv oraz narzędzia
Qt wymagane przez PyQt5:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

W niektórych minimalnych instalacjach środowisko graficzne może wymagać
dodatkowych bibliotek systemowych Qt, np. `libxcb-cursor0`. Zainstaluj
brakujące biblioteki, jeśli system zgłosi błąd ładowania Qt.

W folderze projektu utwórz środowisko i uruchom aplikację:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

W innych dystrybucjach użyj ich menedżera pakietów do instalacji Pythona
3.10+, `venv` i `pip`. Uruchamianie aplikacji w Linux wymaga sesji graficznej.

## Budowanie aplikacji EXE w Windows

Uruchom `build_exe.bat` w Windows. Skrypt zapyta o nazwę pliku EXE (podaj ją
bez rozszerzenia `.exe`); pozostawienie pola pustego wybiera
`PerforacjaDXF`. Następnie skrypt tworzy środowisko `.build-venv`, instaluje
zależności i buduje jednoplikową aplikację. Wynik znajduje się w folderze
`dist`, pod podaną nazwą, np. `dist\MojaPerforacja.exe`. Przy pierwszym
budowaniu wymagane jest połączenie z internetem.

Skrypt buduje wersję dla Windows; nie tworzy pliku wykonywalnego dla Linux.

## Szybki przebieg pracy

1. Kliknij **Otwórz DXF** i wybierz rysunek detalu.
2. Sprawdź podgląd źródłowy oraz komunikaty na dolnym pasku. Jeśli rozmiar
   jest nieprawidłowy, upewnij się, że plik ma poprawnie ustawione jednostki.
3. Ustaw wymiary gotowego detalu, kształt i rozmiar otworu, układ,
   odległości, kąty oraz marginesy.
4. Sprawdź podgląd perforacji. Zmiany parametrów są przeliczane automatycznie.
   Jeśli konfiguracja jest nieprawidłowa, komunikat błędu pojawi się na dole,
   a eksport zostanie wyłączony.
5. Wybierz sposób eksportu perforacji i nazwę pliku, a następnie kliknij
   **Eksportuj DXF**. Program nie pozwala nadpisać aktualnie otwartego pliku
   źródłowego; przed nadpisaniem innego istniejącego pliku prosi o
   potwierdzenie.

## Parametry detalu

### Wymiary

- **Szerokość** i **wysokość** określają wymiary wynikowego detalu w mm.
  Można je edytować niezależnie; zmiana tylko jednej wartości zmienia
  proporcje konturu.
- Wartości są podawane z dokładnością 0,1 mm. Przyciski zwiększania
  i zmniejszania zmieniają wymiar domyślnie o 5 mm.

### Kształt otworu

Program udostępnia:

- **Koło** — parametr to średnica.
- **Kwadrat** — parametr to długość boku.
- **Prostokąt** — parametry to szerokość i wysokość.
- **Trójkąt równoboczny** — parametr to szerokość podstawy.
- **Owal / elipsa** — parametry to szerokość i wysokość.
- **Fasolka** — parametry to całkowita długość i szerokość. Promień
  zaokrąglenia końców wynika z szerokości i jest równy jej połowie. Długość
  musi być równa lub większa od szerokości.
- **Wielokąt foremny** — szerokość oraz liczba boków od 3 do 20.
- **Własny kształt z DXF** — wybierz osobny plik z zamkniętym konturem.
  Kształt jest skalowany do podanej szerokości z zachowaniem proporcji;
  jego wysokość wynika z proporcji wczytanego pliku.

Wymiary kształtów i odstępy podaje się w milimetrach.

### Układ, odległości i kąty

- **Układ prosty (kwadratowy)** rozmieszcza środki otworów w równych
  odstępach poziomo i pionowo.
- **Układ mijankowy** przesuwa co drugi rząd o połowę podziałki.
- **Tryb odległości — odstęp między krawędziami** oznacza minimalną
  szczelinę pomiędzy obrysami sąsiednich otworów. Program dobiera podziałkę
  na podstawie rzeczywistego kształtu i sprawdza, czy otwory nie zachodzą
  na siebie.
- **Tryb odległości — podziałka osiowa** ustawia odległość między środkami
  sąsiednich otworów. W układzie mijankowym podana wartość jest odległością
  po przekątnej do sąsiada w kolejnym rzędzie; odległość między rzędami
  wynosi `podziałka × √3 / 2`.
- **Kąt siatki** obraca układ rozmieszczenia względem detalu.
- **Kąt kształtu względem siatki** obraca sam otwór niezależnie od układu.
  Wartość 0° oznacza, że kształt obraca się razem z siatką, jak w
  dotychczasowym działaniu programu.

### Marginesy

- **Margines od krawędzi zewnętrznej** określa minimalną odległość otworu od
  zewnętrznego obrysu materiału.
- **Margines od krawędzi wewnętrznej / wyspy** określa minimalną odległość
  otworu od wewnętrznych konturów oraz krawędzi wysp materiału.
- Margines jest zachowywany dla całego obrysu otworu, a nie tylko jego środka.
  Wartość 0 mm nie dodaje odstępu od danej grupy krawędzi.

## Import DXF

- Program odczytuje geometrię z przestrzeni **modelspace**. Obsługiwane
  obiekty liniowe (m.in. linie, łuki, okręgi, elipsy i splajny) są
  przekształcane do odcinków z tolerancją aproksymacji 0,05 mm.
- Kontury muszą tworzyć zamknięte, płaskie obszary. Zagnieżdżone kontury są
  interpretowane naprzemiennie jako materiał, otwór wewnętrzny i wyspa
  materiału. Otwartych linii, opisów, wymiarów i innych elementów
  niebędących konturami program nie wykorzystuje do wyznaczania kształtu.
- Jednostki wejściowego DXF są przeliczane na milimetry. Jeśli plik nie
  określa jednostek, program przyjmuje milimetry i wyświetla ostrzeżenie.
  Poprawność skali zależy od jednostek zapisanych w pliku.
- Przy ponownym otwieraniu pliku wyeksportowanego przez program, jeśli istnieją
  warstwy `OBRYS` i `OTWORY`, do obliczeń używane są obiekty z warstwy `OBRYS`.
  Poprzednia perforacja jest pomijana i można ją wygenerować ponownie.
- Program nie odtwarza automatycznie wymiarów, opisów ani pozostałych warstw
  z oryginalnego rysunku. Eksport jest nowym, uproszczonym rysunkiem.

## Eksport i ponowna edycja

Eksportowany DXF używa milimetrów i zawiera:

- zamknięte polilinie obrysu na warstwie `OBRYS`,
- otwory na warstwie `OTWORY` — koła jako okręgi, pozostałe kształty jako
  zamknięte polilinie,
- opcjonalnie perforację zapisaną jako jeden blok `PERFORACJA` wstawiony do
  przestrzeni modelu.

Otwory można eksportować jako osobne obiekty albo jako blok. W obu wariantach
zachowana jest warstwa `OTWORY`, co umożliwia ponowne otwarcie pliku i
wygenerowanie nowej perforacji na podstawie konturu `OBRYS`. Wybór bloku
zmienia sposób organizacji otworów w DXF, nie ich geometrię.

## Podgląd i ograniczenia

- Lewy panel pokazuje rysunek źródłowy, prawy — aktualny podgląd perforacji.
- Dolny pasek pokazuje wymiary, liczbę otworów i stopień prześwitu. Prześwit
  jest szacowany jako łączna powierzchnia otworów podzielona przez pole
  materiału.
- Program ogranicza liczbę otworów do 100 000 i liczbę sprawdzanych punktów
  siatki do 2 000 000, aby uniknąć nadmiernego zużycia pamięci i czasu
  obliczeń. Przy przekroczeniu limitu zwiększ podziałkę lub zmniejsz detal.
- Eksport zawiera geometrię obrysu i perforacji; nie przenosi warstw
  opisowych, wymiarów ani innych danych z wejściowego DXF.

## Rozwiązywanie problemów

- **Plik nie zawiera zamkniętego konturu** — sprawdź w programie CAD, czy
  końce linii łączą się i czy kontur jest zamknięty.
- **Nieprawidłowa skala** — ustaw właściwe jednostki w źródłowym DXF.
  Gdy jednostki są nieokreślone, program zakłada mm.
- **Brak otworów w podglądzie** — zmniejsz margines lub wymiary otworu,
  ewentualnie sprawdź, czy detal ma wystarczająco dużo materiału.
- **Otwory nachodzą na siebie lub mają za mały odstęp** — zwiększ
  podziałkę/odstęp albo zmniejsz otwór.
- **Błąd biblioteki Qt w Linux** — doinstaluj brakujące systemowe biblioteki
  Qt wskazane w komunikacie systemu.
