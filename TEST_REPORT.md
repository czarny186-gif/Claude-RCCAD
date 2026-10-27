# Raport testów RCCAD — 26 października 2026

Aplikację uruchomiono przez lokalny serwer HTTP w Chromium. Potwierdzono HTTP 200,
widoczny obszar CAD i brak błędów JavaScript. Testy regresji: **86/86 zaliczonych**.
Ten sam zestaw uruchomiony na niezmienionym załączniku: **80/86 zaliczonych**.

## Naprawy

- SVG: obrót, pochylenie X/Y oraz obrót osi łuku eliptycznego używały π/36
  zamiast π/180 do przeliczenia stopni na radiany.
- DXF: błędna konwersja kątów łuku oraz dwukrotne zastosowanie skali importu.
- Otwarcie i wyczyszczenie projektu: synchronizacja punktu odniesienia historii
  szkicu i przycisków cofania. Wcześniej automatyczne zapamiętywanie szkicu mogło
  potraktować otwarcie projektu jak edycję i utworzyć nieprawidłową historię.

## Sprawdzony zakres

- Start i renderowanie canvas; przełączanie narzędzi, płaszczyzn i trybów.
- Aktywacja wszystkich wariantów narzędzi szkicu przez ich obsługę przycisków.
- Geometria linii, linii konstrukcyjnych, punktów, prostokątów, prostokątów
  środkowych i trzypunktowych, okręgów, elips, wielokątów, fasolek i łuków.
- Okrąg przez trzy punkty, przez końce średnicy i styczny do dwóch linii;
  odrzucenie współliniowych punktów.
- Przycinanie przy przecięciach i punktach Snap; edycja wymiarów prostokąta
  i cofnięcie tej edycji.
- Wyciągnięcie prostopadłościanu, zakresy jednostronny/symetryczny/dwustronny;
  wyciągnięcie profilu z otworem z kontrolą objętości i zamknięcia siatki.
- Suma, różnica i część wspólna nachodzących prostopadłościanów z kontrolą objętości.
- Zaokrąglenie i fazowanie krawędzi prostopadłościanu z kontrolą zamknięcia siatki
  i ubytku objętości; obrót, przesunięcie z anulowaniem i odbicie bryły.
- Kopiowanie/wklejanie, wycinanie, usuwanie oraz cofanie i ponawianie.
- Kontury tekstu z otworami i polskim znakiem w trzech czcionkach.
- Zapis i odczyt projektu; rzeczywiste pobranie projektu przez okno zapisu.
- Eksport i ponowny import STEP oraz STL ASCII/binarny z kontrolą objętości;
  rzeczywiste pobranie plików we wszystkich trzech formatach przez interfejs.
- Import podstawowych figur SVG, transformacji, łuku eliptycznego oraz elementów
  DXF z kontrolą skali; odrzucenie niepoprawnego SVG, pustego STL i zerowej skali.

## Metoda i ograniczenia

`tests/test_browser.py` uruchamia prawdziwe Chromium. Część testów używa kliknięć
interfejsu i pobierania plików, a część wywołuje funkcje geometrii i sprawdza ich
wyniki. Dostęp do funkcji wewnętrznych jest dodawany wyłącznie w odpowiedzi HTTP
przechwytywanej przez test; aplikacja nie zawiera interfejsu testowego.

To szeroki zestaw scenariuszy, a nie dowód poprawności wszystkich możliwych modeli
CAD. Nie sprawdzono pełnych sekwencji przeciągania każdego narzędzia myszą,
wszystkich kombinacji operacji na złożonych bryłach, ogromnych plików, importu
z każdego zewnętrznego programu ani innych przeglądarek i urządzeń dotykowych.
Natywne okno zapisu na dysk wymaga ręcznego sprawdzenia; automatycznie sprawdzono
ścieżkę pobierania plików. STL/STEP przetestowano na prostym modelu kontrolnym.

Poprawiony plik zachowuje dotychczasową nazwę. Oryginalny przesłany załącznik
pozostał nienaruszony. Aktualny program jest udostępniany w repozytorium GitHub `czarny186-gif/RCCAD` jako `RCCAD.html`.

## Poprawki zaokrąglania i fazowania po zgłoszeniu użytkownika

Dodatkowy zestaw `python tests/test_edge_tools.py`: **20/20 zaliczonych**.
Dotychczasowy zestaw: **86/86 zaliczonych** po tych zmianach.

Potwierdzone problemy i poprawki:

- Zmiana rodzaju operacji usuwała zaznaczenie krawędzi. Teraz wybór pozostaje.
- Wybór różnych odcinków tej samej obwiedni mógł dublować cały łańcuch.
  Teraz ponowny wybór dowolnego jego odcinka odznacza ten sam łańcuch.
- Po modyfikacji pierwszej krawędzi zmieniał się środek sąsiedniej krawędzi.
  Teraz wyszukiwanie uwzględnia zachowany odcinek na pierwotnej prostej,
  a modyfikacja pierwotnie prostej krawędzi nie rozszerza się automatycznie
  na łuk utworzony przez poprzednią operację.
- Wypukłe modele z prostymi krawędziami korzystają z bezpośredniego przycinania
  płaszczyznami zamiast ogólnych operacji Boolean. Każdy wynik wymaga dodatniej
  objętości, jej zmniejszenia i szczelnej, poprawnie zorientowanej siatki.
- Podgląd nie wykonuje już spawania i naprawiania siatki narzędzia przy każdym
  wpisanym znaku; używa lżejszej reprezentacji i mniejszej liczby segmentów.
- Ogólna ścieżka obliczeń krawędzi sprawdza limit czasu 1,5 s w punktach kontroli.
  Nieudana lub przerwana operacja przywraca model. Nie jest to ścisła gwarancja
  czasu rzeczywistego — pojedynczy etap między kontrolami może trwać dłużej.
- Za duży rozmiar jest wstępnie odrzucany. Częściowo wykonane zestawy krawędzi
  wyświetlają liczbę pominiętych pozycji zamiast sugerować wykonanie całości.

Testy obejmują rzeczywiste kliknięcie krawędzi i przycisku „Zastosuj”, zmianę
rodzaju operacji po zaznaczeniu, podgląd, kontrolę objętości i szczelności oraz
cofanie i ponawianie. Przetestowano prostopadłościan, obrócony prostopadłościan,
walec, graniastosłup sześciokątny i dwie sąsiednie krawędzie.
Osobno sprawdzono wszystkie 12 ostrych krawędzi prostopadłościanu, 18 krawędzi
sześciokątnego graniastosłupa i obie obwiednie walca dla obu operacji.

W tej maszynie bezpośrednia modyfikacja pojedynczej krawędzi zajmowała około
0,2–3 ms na modelach wielościennych, a obwiedni walca około 16–96 ms.
To pomiary silnika na modelach testowych; kliknięcie, podgląd i rysowanie mają
własny koszt. Sprawdzono również szybkie odrzucenie promienia 1000 mm na modelu
20 mm oraz wycofanie operacji po wyczerpaniu budżetu czasu.

Złożone importowane siatki, krawędzie wklęsłe i przecinające się zaokrąglenia
nadal mogą wymagać mniejszego promienia lub wykonywania operacji osobno.
Nie odtworzono zgłoszenia „na wszystkich” dla pojedynczej krawędzi prostych brył;
potwierdzono i usunięto opisane problemy zaznaczenia i sąsiednich krawędzi.

## Wybór pojedynczej krawędzi po kolejnym zgłoszeniu ze zrzutem

Odtworzono wybór prostej krawędzi sąsiadującej z wcześniejszym zaokrągleniem.
Program rozszerzał ją na łańcuch 28 punktów przechodzący przez narożnik.
Oba nowe testy tego przypadku nie przechodziły przed poprawką.

Usunięto rozszerzanie długiej prostej krawędzi na sąsiedni łuk.
Łączenie odcinków krzywej zatrzymuje się na ostrym załamaniu lub dużej różnicy
ich długości; zamknięte obwiednie walca nadal działają jako pojedyncza krzywa.

Zwykły klik wybiera jedną krawędź, zastępując wcześniejszy wybór. Shift + klik
pozwala dodawać i odznaczać kolejne. Ponowny zwykły klik jedynej wybranej
krawędzi usuwa zaznaczenie. Zaktualizowano wskazówkę w panelu.

Weryfikacja: **23/23** testy narzędzi krawędzi oraz **86/86** wcześniejszych
scenariuszy. Nowe sprawdzenia obejmują kliknięcie prostej krawędzi obok istniejącego
zaokrąglenia, jej zaokrąglenie i fazowanie przez przycisk „Zastosuj”, szczelność
wyniku oraz normalne kliknięcia i Shift + klik. Brak błędów JavaScript.

## Otwór i górne zaokrąglenia przed modyfikacją boków

Zgłoszenie: pionowa krawędź nie daje się zmodyfikować po wcześniejszym
zaokrągleniu otworu i zewnętrznych krawędzi na górnej płaszczyźnie.

Wcześniej szybkie przycinanie wymagało globalnie wypukłego modelu. Obecność
otworu wykluczała tę ścieżkę, a zakrzywione zakończenia bocznej krawędzi utrudniały
lokalną operację. Ogólna operacja Boolean zwiększała liczbę ścian i mogła
przekraczać limit czasu. W próbie kostki 20 mm, otworu o promieniu 4 mm i
zaokrągleń 3 mm potwierdzono przekroczenie limitu dla bocznej krawędzi po
wcześniejszych modyfikacjach. Ten wymiar leży dodatkowo na granicy zetknięcia
zaokrągleń górnych i otworu, więc jest szczególnie wrażliwy numerycznie.

Szybkie przycinanie działa teraz także dla zewnętrznej krawędzi modelu z otworem,
jeśli obie sąsiednie płaszczyzny podpierają cały model. Nie wymaga wypukłości
ścian wewnętrznych. Punkty styczności są sprawdzane względem wnętrza bryły.
Granica nowego przekroju jest odtwarzana z połączeń przeciętych ścian, a nie
sortowana wokół środka. Niejednoznaczne lub rozłączne pętle są odrzucane;
operacja nie może połączyć ich w zaślepkę zasłaniającą otwór. Pozostają kontrola
szczelności, objętości, zasięgu cięcia i limit czasu. Poprawiono także obsługę
punktów leżących w tolerancji płaszczyzny cięcia.

Testy: **26/26** scenariuszy krawędzi oraz **86/86** wcześniejszych scenariuszy.
Nowe testy przygotowują kostkę 30 mm, przelotowy otwór o średnicy 12 mm
(80 odcinków obwodu) i promień 3 mm. Kolejno wykonują zaokrąglenie górnej
krawędzi otworu, czterech zewnętrznych górnych krawędzi oraz wszystkich czterech
bocznych. Sprawdzono osobno zaokrąglanie i fazowanie boków. Pierwsza boczna
operacja jest wybierana i zatwierdzana rzeczywistymi kliknięciami w Chromium.

Każdy etap wymaga zmniejszenia objętości i poprawnie zamkniętej siatki.
Sprawdzono również drożność osi otworu, niezmieniony przekrój jego części
środkowej oraz cofanie i ponawianie bocznej operacji. Osobny test sprawdza
odrzucenie dwóch rozłącznych pętli przekroju. Bardzo bliskie lub przecinające
się zaokrąglenia nadal mogą wymagać zmniejszenia promienia.

## Czarne spoiny w narożnikach po trzech zaokrągleniach

Odtworzono czarne kreski w kształcie Y na zaokrąglonej kostce. Były to
rzeczywiste ostre przecięcia trzech cylindrycznych powierzchni, a nie błąd
koloru czy bufora głębi. Nie zmieniono progu rozpoznawania ostrych krawędzi.

Dla trzech jednakowych promieni na wzajemnie prostopadłych zewnętrznych
krawędziach program tworzy teraz sferyczne połączenie. Operacja jest lokalna,
sprawdza zamknięcie i objętość siatki i pozostawia model bez tej poprawki,
jeśli geometria nie spełnia warunków bezpiecznego rozpoznania. Narożniki są
rozpoznawane z geometrii, bez zależności od historii operacji. Dzięki temu
wczytanie starszego projektu może usunąć już zapisane spoiny; komunikat otwarcia
informuje o wykonanej naprawie. Naprawa starszych brył ma limit czasu 700 ms
na bryłę i przy braku bezpiecznego wyniku zachowuje oryginalną geometrię.

Weryfikacja: **13/13** nowych scenariuszy narożników, **26/26** scenariuszy
narzędzi krawędzi i **86/86** pozostałych scenariuszy, łącznie **125/125**.
Nowy zestaw uruchamia się poleceniem `python tests/test_corner_blends.py`.

- Kostka 30 mm z 12 zaokrąglonymi krawędziami o promieniu 3 mm: brak ostrych
  spoin we wszystkich ośmiu narożnikach, poprawnie zamknięta siatka.
- Objętość porównana z analityczną objętością zaokrąglonego prostopadłościanu;
  względny błąd poniżej 0,01%. Maksymalne odchylenie wierzchołków narożników od
  sfery o promieniu 3 mm wyniosło około 0,021 mm przy aktualnej aproksymacji.
- Zachowane prawdziwe ostre krawędzie zwykłej kostki i fazowania.
- Kolejne operacje zaokrąglania oraz naprawa wczytanego projektu przez interfejs.
- Naprawa narożników po obrocie i przesunięciu starszej bryły.
- Obraz Canvas 2D: w kontrolowanym fragmencie przy narożniku liczba czarnych
  pikseli spadła z 31 do 0. Osobno wykonano test rzeczywistej ścieżki WebGL
  przez SwiftShader z obsługiwaną opcją `?forcegl`: brak czarnej spoiny.
- Eksport i ponowny import STL binarnego, STL ASCII i STEP: szczelna siatka,
  brak odtworzonych ostrych spoin, względny błąd objętości poniżej 0,01%.

Automatyczne połączenie dotyczy rozpoznanych, równych promieni przy narożnikach
prostokątnych. Nie oznacza ogólnej obsługi dowolnych promieni i dowolnych kątów.

## HTML: wycinanie profilu po drugim wyciągnięciu — 27 października 2026

Odtworzono zgłoszenie w starszym programie HTML: podstawa, drugie wyciągnięcie
na górnej ścianie, połączenie, a następnie wycięcie kolejnym profilem.
Przełączenie operacji z Nowa/Połącz na Wytnij zmieniało znak wpisanej odległości,
chociaż kierunek wycięcia był już odwracany względem normalnej ściany. Te dwa
odwrócenia znosiły się. Przy głębokości 50 mm profil na wysokości 40 mm
wyciągał narzędzie do wysokości 90 mm zamiast przecinać model. Przykładowa
objętość pozostawała 31 000 mm³, a operacja mimo tego była zatwierdzana.

Poprawki:

- Zmiana rodzaju operacji pozostawia wpisaną odległość. Dodatnia głębokość
  wycięcia na wskazanej ścianie kieruje narzędzie do wnętrza. W trybie dwóch
  stron wartości pierwszej i drugiej strony nie są zamieniane.
- Wybieranie profilu uwzględnia najpierw rzeczywistą głębokość pod kursorem,
  a dopiero na tej samej płaszczyźnie powierzchnię komórki. Mniejszy stary szkic
  pod modelem nie przechwytuje wyboru nowego, większego profilu na górze.
- Narzędzie tylko dotykające bryły lub operacja bez zmiany objętości nie tworzą
  pozornego wycięcia ani wpisu historii. Panel pozostaje dostępny do korekty.
- Nieszczelny wynik Boolean nie zastępuje modelu: operacja jest wycofywana.
- Panel wyciągnięcia wyjaśnia dodatni kierunek wycinania.

Weryfikacja: **19/19 nowych scenariuszy** oraz **125/125 wcześniejszych**,
łącznie **144/144**. Zestaw `python tests/test_stacked_extrusion.py` uruchamia
Chromium i korzysta z rzeczywistego wyboru ściany, kliknięcia profilu, zmiany
operacji w liście i przycisku Zastosuj.

Sprawdzono prostokąt, okrąg, elipsę, sześciokąt, fasolkę, prostokąt trzypunktowy,
trójkąt i wklęsły profil L połączonej bryły. Sprawdzono objętość usuniętego
materiału, szczelność siatki, cofanie i ponawianie, wszystkie sześć kierunków
ścian, niezależne głębokości dwóch stron, brak zmian przy narzędziu skierowanym
na zewnątrz oraz wycofanie nieprawidłowego wyniku. Dla profili krzywoliniowych
uwzględniono dotychczasową aproksymację siatki programu HTML.

Ten sam nowy zestaw na pliku sprzed poprawki: **4/19 zaliczonych**. Poprawki
tej sekcji dotyczą HTML; aplikacja EXE nie została zmieniona w tym zadaniu.
