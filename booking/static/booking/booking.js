// Service changes refresh eligible barbers; the server validates every selection.
const visitSelection = document.getElementById("visit-selection");
if (visitSelection) {
    visitSelection.elements.service.addEventListener("change", () => {
        visitSelection.elements.barber.value = "";
        visitSelection.submit();
    });
}
