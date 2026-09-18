// TradeVerse - simple front-end helper script

function togglePassword(inputId, toggleEl) {
    var input = document.getElementById(inputId);
    if (input.type === "password") {
        input.type = "text";
        toggleEl.textContent = "HIDE";
    } else {
        input.type = "password";
        toggleEl.textContent = "SHOW";
    }
}

// Auto-hide flash messages after a few seconds
window.addEventListener("load", function () {
    var flashes = document.querySelectorAll(".flash");
    flashes.forEach(function (el) {
        setTimeout(function () {
            el.style.transition = "opacity 0.5s ease";
            el.style.opacity = "0";
            setTimeout(function () {
                el.style.display = "none";
            }, 500);
        }, 4000);
    });
});

// Basic client side validation for register form
function validateRegisterForm() {
    var phone = document.getElementById("phone").value.trim();
    var password = document.getElementById("password").value;

    if (phone.length < 10) {
        alert("Please enter a valid phone number (at least 10 digits).");
        return false;
    }

    if (password.length < 6) {
        alert("Password must be at least 6 characters long.");
        return false;
    }

    return true;
}
