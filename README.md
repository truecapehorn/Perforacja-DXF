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
- Margines jest zachowywany pomiędzy krawędzią detalu (także konturem
  wewnętrznym) a krawędzią otworu, niezależnie od kształtu otworu.
- Otwory mogą mieć kształt koła, kwadratu, prostokąta, trójkąta
  równobocznego, elipsy lub wielokąta foremnego (3–20 boków). Można też
  wczytać własny kształt z osobnego pliku DXF. Zamknięte kontury są
  interpretowane z uwzględnieniem zagnieżdżeń, a kształt jest skalowany do
  podanej szerokości z zachowaniem proporcji.
- Odstęp oznacza szczelinę pomiędzy otworami; podziałka oznacza odległość
  środek–środek. W układzie mijankowym podziałka jest odległością po przekątnej
  między najbliższymi środkami: odległość pozioma w rzędzie pozostaje równa
  podziałce, a odstęp rzędów wynosi `podziałka × √3 / 2`. Dla układu prostego
  podziałka pozostaje jednakowa w poziomie i pionie. Odstęp jest sprawdzany
  pomiędzy rzeczywistymi obrysami; program nie pozwala na nachodzenie otworów.
- Eksport tworzy nowy, uproszczony DXF w milimetrach: obrysy zapisuje jako
  zamknięte polilinie, a otwory jako okręgi lub zamknięte polilinie na warstwie
  `OTWORY`.
- Dolny pasek pokazuje liczbę otworów i stopień prześwitu, obliczany jako
  łączna powierzchnia otworów podzielona przez powierzchnię materiału.

To wersja startowa — warstwy opisowe i wymiary z oryginalnego rysunku nie są
przenoszone do pliku wynikowego.
