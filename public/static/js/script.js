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

// Real-time password requirement and phone validation
document.addEventListener("DOMContentLoaded", function () {
    var passwordInput = document.getElementById("password");
    var phoneInput = document.getElementById("phone");

    if (passwordInput && document.getElementById("pwRequirements")) {
        passwordInput.addEventListener("input", function () {
            var val = passwordInput.value;

            updateRule("rule-lower", /[a-z]/.test(val));
            updateRule("rule-upper", /[A-Z]/.test(val));
            updateRule("rule-number", /[0-9]/.test(val));
            updateRule("rule-special", /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`~]/.test(val));
        });
    }

    if (phoneInput) {
        phoneInput.addEventListener("input", function () {
            // Only allow digits and cap at 14 characters
            this.value = this.value.replace(/\D/g, "").slice(0, 14);
        });
    }
});

function updateRule(elementId, isValid) {
    var el = document.getElementById(elementId);
    if (!el) return;
    var icon = el.querySelector(".rule-icon");
    if (isValid) {
        el.classList.add("valid");
        if (icon) icon.innerHTML = "&#10003;"; // checkmark
    } else {
        el.classList.remove("valid");
        if (icon) icon.innerHTML = "&#10007;"; // cross
    }
}

// Client side validation for register form
function validateRegisterForm() {
    var phoneInput = document.getElementById("phone");
    var passwordInput = document.getElementById("password");

    var phoneDigits = (phoneInput ? phoneInput.value : "").trim().replace(/\D/g, "");
    var password = passwordInput ? passwordInput.value : "";

    if (phoneDigits.length < 10 || phoneDigits.length > 14) {
        alert("Phone number length must be between 10 and 14 digits.");
        if (phoneInput) phoneInput.focus();
        return false;
    }

    if (!/[a-z]/.test(password)) {
        alert("Password must include at least one lowercase letter (a-z).");
        if (passwordInput) passwordInput.focus();
        return false;
    }

    if (!/[A-Z]/.test(password)) {
        alert("Password must include at least one uppercase letter (A-Z).");
        if (passwordInput) passwordInput.focus();
        return false;
    }

    if (!/[0-9]/.test(password)) {
        alert("Password must include at least one number (0-9).");
        if (passwordInput) passwordInput.focus();
        return false;
    }

    if (!/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`~]/.test(password)) {
        alert("Password must include at least one special character (!@#$%^&*...).");
        if (passwordInput) passwordInput.focus();
        return false;
    }

    return true;
}

// Refresh login captcha code
function refreshCaptcha() {
    var box = document.getElementById("captchaBox");
    if (!box) return;
    box.textContent = "...";
    fetch("/api/captcha")
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data && data.captcha) {
                box.textContent = data.captcha;
                var input = document.getElementById("captcha");
                if (input) {
                    input.value = "";
                    input.focus();
                }
            }
        })
        .catch(function () {
            box.textContent = "TR78K";
        });
}

