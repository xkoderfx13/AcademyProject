document.addEventListener('DOMContentLoaded', () => {
    const reportCards = document.querySelectorAll('.report-card-header');

    reportCards.forEach(header => {
        header.addEventListener('click', () => {
            header.parentElement.classList.toggle('open');
        });
    });
});

