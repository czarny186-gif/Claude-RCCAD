"""Samouczek RCCAD (menu Plik → Pomoc): tematy po lewej, opis z ilustracją po prawej."""
from __future__ import annotations
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QScrollArea, QVBoxLayout, QPushButton, QFrame
from . import icons

TOPICS = [
    ('new', 'Start', 'Jak zacząć', [
        'Po uruchomieniu widzisz trzy płaszczyzny środkowe (XY, XZ, YZ). Obracaj widok lewym przyciskiem myszy, przesuwaj prawym lub Shift + lewy, zoom kółkiem.',
        'Pasek narzędzi u góry: Plik, Szkic, Wyciągnij, Połącz, Edytuj (zaokrąglanie, fazowanie), Lustro.',
        'Cofanie i ponawianie: strzałki w prawym górnym rogu albo Ctrl+Z / Ctrl+Y. Przycisk z warstwami pokazuje płaszczyzny, przycisk obok włącza przezroczyste bryły.']),
    ('sketch', 'Szkic', 'Rysowanie na płaszczyźnie lub ścianie', [
        'Kliknij Szkic, potem płaszczyznę środkową albo dowolną płaską ścianę bryły (podświetli się na pomarańczowo). Można też kliknąć ścianę kostki widoku.',
        'Wybierz kształt: linia, prostokąt, okrąg, łuk, wielokąt, tekst. Rysuj klik–klik. Kursor przyciąga się do punktów, środków, krawędzi i przecięć (znacznik pokazuje typ).',
        'Esc lub prawy przycisk kończy bieżącą linię i zostawia ją. Kształty nachodzące na siebie dzielą się na obszary, które można osobno wyciągać. Narzędzie Przytnij usuwa odcinek między przecięciami.']),
    ('extrude', 'Wyciągnij', 'Wyciąganie i wycinanie', [
        'Kliknij Wyciągnij i wskaż zamknięty profil szkicu, obszar między liniami albo płaską ścianę bryły. Wybrana powierzchnia świeci się. Shift + klik dodaje kolejne profile.',
        'Pociągnij strzałkę z grotem lub wpisz odległość. Podgląd odświeża się na żywo. Operacja: Nowa bryła, Połącz, Wytnij, Wspólna część. Kierunek: jedna strona, symetrycznie, dwie strony.',
        'Enter zatwierdza, Esc anuluje.']),
    ('bool', 'Połącz', 'Operacje logiczne na bryłach', [
        'Wybierz działanie: suma, różnica albo część wspólna. Kliknij bryłę bazową (niebieska), potem bryły-narzędzia (pomarańczowe). Ponowne kliknięcie odznacza.',
        'Opcja Zachowaj bryły-narzędzia pozostawia oryginały. Podgląd wyniku widać od razu.']),
    ('fillet', 'Zaokrąglanie i fazowanie', 'Krawędzie', [
        'Kliknij krawędź. Shift + klik dodaje kolejne, Ctrl + klik zaznacza cały łańcuch styczny.',
        'Rozmiar zmieniasz strzałką lub wpisując wartość. Zielony podgląd dodaje materiał, pomarańczowy go usuwa.']),
    ('mirror', 'Lustro', 'Odbicie lustrzane', [
        'Krok 1: kliknij bryłę lub element szkicu do odbicia. Krok 2: kliknij ścianę, która ma być lustrem. Odbicie powstaje po drugiej stronie tej ściany.',
        'Zachowaj oryginał tworzy kopię, Połącz z oryginałem skleja obie bryły w jedną.']),
    ('x_pat_rect', 'Szyk', 'Powielanie obiektów', [
        'Kliknij bryłę lub szkic, wybierz rodzaj: prostokątny (ilość i odstęp w osiach X, Y, Z), kołowy (oś, ilość i kąt całkowity) albo wzdłuż linii (kliknij linię szkicu lub krawędź bryły).',
        'Kopie widać na bieżąco i zmieniają się razem z wartościami. Połącz kopie w jedną bryłę skleja wynik. Enter zatwierdza.']),
    ('sym', 'Przesuń i obróć', 'Transformacje', [
        'Zaznacz bryłę lub szkic. Przesuwanie: pociągnij kolorową strzałkę osi, kwadrat płaszczyzny albo złap samą bryłę lewym przyciskiem.',
        'Obrót: pociągnij kolorowy pierścień wokół osi. Wartości można też wpisać. Strzałki dopasowują się do ustawienia kamery.']),
    ('one', 'Widok', 'Kostka i skróty', [
        'Kostka w prawym górnym rogu: klik w ścianę ustawia widok z tej strony, klik w krawędź lub róg widok ukośny. Domek wraca do widoku głównego.',
        'Skróty: Ctrl+N nowy, Ctrl+O otwórz, Ctrl+S zapisz, Ctrl+Z cofnij, Ctrl+Y ponów, Enter zatwierdź, Esc anuluj.']),
]


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Pomoc — samouczek RCCAD')
        self.resize(860, 560)
        self.setStyleSheet('QDialog{background:#f4f7fb;} QListWidget{background:#ffffff;border:1px solid #d6e0ea;border-radius:10px;padding:6px;outline:0;}'
                           'QListWidget::item{padding:8px;border-radius:8px;} QListWidget::item:selected{background:#dcebfb;color:#17314a;}'
                           'QLabel#hbody{color:#27415a;font-size:14px;} QLabel#htitle{font-size:22px;font-weight:800;color:#17314a;}')
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)
        self.list = QListWidget()
        self.list.setFixedWidth(230)
        self.list.setIconSize(QSize(34, 34))
        for kind, title, sub, _ in TOPICS:
            item = QListWidgetItem(icons.badge(kind, icons.BLUE, 34), f'{title}\n{sub}')
            item.setSizeHint(QSize(200, 52))
            self.list.addItem(item)
        root.addWidget(self.list)
        right = QVBoxLayout()
        self.head = QLabel()
        self.head.setObjectName('htitle')
        self.pic = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.pic)
        top.addWidget(self.head, 1)
        right.addLayout(top)
        card = QFrame()
        card.setStyleSheet('QFrame{background:#ffffff;border:1px solid #d6e0ea;border-radius:12px;}')
        cl = QVBoxLayout(card)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.body = QLabel()
        self.body.setObjectName('hbody')
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.body.setStyleSheet('border:none;background:transparent;padding:8px;')
        scroll.setWidget(self.body)
        cl.addWidget(scroll)
        right.addWidget(card, 1)
        close = QPushButton('Zamknij')
        close.clicked.connect(self.accept)
        right.addWidget(close, 0, Qt.AlignRight)
        root.addLayout(right, 1)
        self.list.currentRowChanged.connect(self.show_topic)
        self.list.setCurrentRow(0)

    def show_topic(self, row):
        if row < 0:
            return
        kind, title, sub, lines = TOPICS[row]
        self.head.setText(f'{title}\n')
        self.head.setText(title)
        self.pic.setPixmap(icons.badge(kind, icons.BLUE, 56))
        self.body.setText(''.join(f'<p style="margin:0 0 12px 0;line-height:140%">{i + 1}. {t}</p>' for i, t in enumerate(lines)))
