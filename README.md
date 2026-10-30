# Perforacja DXF

Pierwsza wersja aplikacji Windows do tworzenia perforowanych detali z plików
DXF. Interfejs graficzny wykorzystuje PyQt5.

## Uruchomienie ze źródeł

Wymagany jest Python 3.10 lub nowszy.

```powershell
python -m pip install -r requirements.txt
python app.py
```

Po uruchomieniu otwórz rysunek przyciskiem **Otwórz DXF**.

## Budowanie aplikacji EXE

Uruchom `build_exe.bat` w systemie Windows. Gotowy plik zostanie zapisany jako
`dist\PerforacjaDXF.exe`. Wymagane jest połączenie z internetem przy pierwszym
budowaniu, aby pobrać biblioteki Pythona.

## Obsługa

- Importowane są zamknięte, płaskie kontury z modelspace. Linie, łuki,
  okręgi, elipsy i splajny są zamieniane na polilinie z tolerancją 0,05 mm.
- Zagnieżdżone kontury są traktowane naprzemiennie jako materiał, otwór
  wewnętrzny i ewentualna wyspa materiału.
- Jednostki wejściowego DXF są przeliczane na milimetry. Gdy plik nie określa
  jednostek, przyjmowane są milimetry, a aplikacja pokazuje ostrzeżenie.
- Szerokość i wysokość gotowego detalu można podać z dokładnością 0,1 mm.
  Przyciski zmiany wartości zwiększają ją domyślnie o 5 mm.
  Wymiary X i Y są ustawiane niezależnie, więc zmiana tylko jednego z nich
  może zmienić proporcje detalu.
- Osobno ustawia się margines od krawędzi zewnętrznej oraz od krawędzi
  wewnętrznych i wysp materiału.
- Otwory mogą mieć kształt koła, kwadratu, prostokąta, trójkąta
  równobocznego, elipsy, fasolki (długość, szerokość i promień zaokrąglenia)
  lub wielokąta foremnego (3–20 boków). Promień fasolki nie może przekraczać
  połowy jej krótszego wymiaru. Można też wczytać własny kształt z
  osobnego pliku DXF. Zamknięte kontury są interpretowane z uwzględnieniem
  zagnieżdżeń, a kształt jest skalowany do podanej szerokości z zachowaniem
  proporcji.
- Kąt siatki i kąt kształtu względem siatki są niezależne. Domyślne 0° kąta
  względnego zachowuje dotychczasowe obracanie otworów razem z siatką.
- Odstęp oznacza szczelinę pomiędzy otworami; podziałka oznacza odległość
  środek–środek. W układzie mijankowym podziałka jest odległością po przekątnej
  między najbliższymi środkami: odległość pozioma w rzędzie pozostaje równa
  podziałce, a odstęp rzędów wynosi `podziałka × √3 / 2`. Dla układu prostego
  podziałka pozostaje jednakowa w poziomie i pionie. Odstęp jest sprawdzany
  pomiędzy rzeczywistymi obrysami; program nie pozwala na nachodzenie otworów.
- Eksport tworzy nowy, uproszczony DXF w milimetrach: obrysy zapisuje jako
  zamknięte polilinie na warstwie `OBRYS`, a otwory jako okręgi lub zamknięte
  polilinie na warstwie `OTWORY`. Otwory można zapisać osobno albo jako jeden
  blok `PERFORACJA`. Ponowne otwarcie takiego pliku wczytuje kontur z warstwy
  `OBRYS` i pomija wcześniejsze otwory, dzięki czemu można wygenerować
  perforację z nowymi parametrami.
- Dolny pasek pokazuje liczbę otworów i stopień prześwitu, obliczany jako
  łączna powierzchnia otworów podzielona przez powierzchnię materiału.

To wersja startowa — warstwy opisowe i wymiary z oryginalnego rysunku nie są
przenoszone do pliku wynikowego.
