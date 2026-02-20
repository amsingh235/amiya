/* ============================================================
   MAIN.JS — Scroll animations, tagline rotation, nav, form
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

  /* ----------------------------------------------------------
     1. SCROLL ANIMATIONS — Intersection Observer
     Watches all .fade-up and .fade-in elements.
     Adds .visible once when each enters the viewport (fires once).
  ---------------------------------------------------------- */
  const animObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        animObserver.unobserve(entry.target); // fire once, don't re-animate on scroll-back
      }
    });
  }, { threshold: 0.15 });

  document.querySelectorAll('.fade-up, .fade-in').forEach(el => {
    animObserver.observe(el);
  });


  /* ----------------------------------------------------------
     2. SKILL BAR ANIMATIONS — Separate observer
     Sets inline width from data-width when the bar scrolls into view.
     Uses higher threshold (0.3) so bars start filling while visible.
  ---------------------------------------------------------- */
  const skillObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const targetWidth = entry.target.dataset.width;
        if (targetWidth) {
          entry.target.style.width = targetWidth;
        }
        skillObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.3 });

  document.querySelectorAll('.skill-bar').forEach(bar => {
    skillObserver.observe(bar);
  });


  /* ----------------------------------------------------------
     3. TAGLINE ROTATION
     Cycles through role labels with a smooth opacity fade.
     Container stays the same size (pre-set to longest word's width)
     to prevent hero layout from jumping.
  ---------------------------------------------------------- */
  const roles = [
    'Business Analyst',
    'Data Enthusiast',
    'AI Explorer',
    'Growth-Oriented'
  ];

  const rotator = document.getElementById('taglineRotator');
  if (rotator) {
    let currentIndex = 0;

    // Pre-measure the longest word so the container never jumps width
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const computedStyle = window.getComputedStyle(rotator);
    ctx.font = `${computedStyle.fontWeight} ${computedStyle.fontSize} ${computedStyle.fontFamily}`;
    let maxWidth = 0;
    roles.forEach(role => {
      const w = ctx.measureText(role).width;
      if (w > maxWidth) maxWidth = w;
    });
    rotator.style.minWidth = Math.ceil(maxWidth) + 'px';
    rotator.style.display = 'inline-block';
    rotator.style.textAlign = 'left';

    const rotateTo = (index) => {
      // Fade out
      rotator.style.opacity = '0';

      setTimeout(() => {
        rotator.textContent = roles[index];
        // Fade in
        rotator.style.opacity = '1';
      }, 400); // matches half the CSS transition duration
    };

    // Start cycling after initial pause
    setInterval(() => {
      currentIndex = (currentIndex + 1) % roles.length;
      rotateTo(currentIndex);
    }, 2600);
  }


  /* ----------------------------------------------------------
     4. NAVBAR ACTIVE STATE
     Highlights the nav link matching the section currently in view.
     Uses scrollY vs section offsetTop ranges (more accurate than
     per-section observers for tall sections).
  ---------------------------------------------------------- */
  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.nav-link');

  const setActiveNav = () => {
    const scrollY = window.scrollY + 100; // offset for sticky nav height

    sections.forEach(section => {
      const top = section.offsetTop;
      const bottom = top + section.offsetHeight;
      const id = section.getAttribute('id');

      if (scrollY >= top && scrollY < bottom) {
        navLinks.forEach(link => {
          link.classList.remove('active');
          if (link.getAttribute('href') === `#${id}`) {
            link.classList.add('active');
          }
        });
      }
    });
  };

  window.addEventListener('scroll', setActiveNav, { passive: true });
  setActiveNav(); // run once on load


  /* ----------------------------------------------------------
     5. MOBILE NAV TOGGLE
     Opens/closes the mobile menu on hamburger click.
     Closes automatically when a nav link is clicked.
  ---------------------------------------------------------- */
  const navToggle = document.getElementById('navToggle');
  const navLinksList = document.getElementById('navLinks');

  if (navToggle && navLinksList) {
    navToggle.addEventListener('click', () => {
      navLinksList.classList.toggle('open');

      // Animate hamburger to X
      const spans = navToggle.querySelectorAll('span');
      if (navLinksList.classList.contains('open')) {
        spans[0].style.cssText = 'transform: rotate(45deg) translate(5px, 5px)';
        spans[1].style.cssText = 'opacity: 0';
        spans[2].style.cssText = 'transform: rotate(-45deg) translate(5px, -5px)';
      } else {
        spans.forEach(s => s.style.cssText = '');
      }
    });

    // Close menu when a link is clicked (mobile UX)
    navLinksList.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        navLinksList.classList.remove('open');
        navToggle.querySelectorAll('span').forEach(s => s.style.cssText = '');
      });
    });
  }


});
