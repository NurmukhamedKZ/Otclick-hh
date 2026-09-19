from app.hh.vacancy_page import extract_description


def test_extract_description_from_hh_data_qa_container():
    html = """
    <html><body>
      <div data-qa="other">ignore me</div>
      <div data-qa="vacancy-description">
        <p>Ищем CIO.</p>
        <p>Задачи:</p>
        <ul><li>трансформация бизнеса</li><li>развитие команды</li></ul>
      </div>
      <div>outside</div>
    </body></html>
    """

    text = extract_description(html)

    assert "Ищем CIO." in text
    assert "Задачи:" in text
    assert "трансформация бизнеса" in text
    assert "развитие команды" in text
    assert "ignore me" not in text
    assert "outside" not in text


def test_extract_description_decodes_entities_and_breaks_lines():
    html = (
        '<div data-qa="vacancy-description">'
        'CIO &amp; CDTO<br>10&nbsp;млрд ₽<p>Рост &gt; 20%</p>'
        '</div>'
    )

    text = extract_description(html)

    assert "CIO & CDTO" in text
    assert "10\xa0млрд ₽" in text
    assert "Рост > 20%" in text
    assert "\n" in text


def test_extract_description_missing_container_is_empty():
    assert extract_description("<html><body>no vacancy here</body></html>") == ""
