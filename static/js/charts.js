'use strict';
// Define chart colors
var chartColors = {
    green: '#75c181',
    gray: '#a9b5c9',
    text: '#252930',
    border: '#e7e9ed'
};

// Generate chart with dynamic data
function generateDynamicChart() {
    // Fetch data from Flask API
    fetch('/api/drowning_events_per_day')
        .then(response => response.json())
        .then(data => {
            // Update chart data
            window.myBar.data.labels = data.labels;
            window.myBar.data.datasets[0].data = data.data;

            // Update chart title if needed
            window.myBar.options.title.text = 'Drowning Events This Week'; // Optional

            // Update chart
            window.myBar.update();
        })
        .catch(error => {
            console.error('Error fetching data:', error);
        });
}

// Initialize chart on load
window.addEventListener('load', function(){
    var barChartConfig = {
        type: 'bar',
        data: {
            labels: [], // Will be populated with day labels from API
            datasets: [{
                label: 'Drowning Events',
                backgroundColor: chartColors.green,
                borderColor: chartColors.green,
                borderWidth: 1,
                maxBarThickness: 16,
                data: [] // Will be populated with data from API
            }]
        },
        options: {
            responsive: true,
            aspectRatio: 1.5,
            legend: {
                position: 'bottom',
                align: 'end',
            },
            title: {
                display: true,
                text: 'Drowning Events This Week'
            },
            tooltips: {
                mode: 'index',
                intersect: false,
                titleMarginBottom: 10,
                bodySpacing: 10,
                xPadding: 16,
                yPadding: 16,
                borderColor: chartColors.border,
                borderWidth: 1,
                backgroundColor: '#fff',
                bodyFontColor: chartColors.text,
                titleFontColor: chartColors.text,
            },
            scales: {
                xAxes: [{
                    display: true,
                    gridLines: {
                        drawBorder: false,
                        color: chartColors.border,
                    },
                }],
                yAxes: [{
                    display: true,
                    gridLines: {
                        drawBorder: false,
                        color: chartColors.border,
                    },
                    ticks: {
                        beginAtZero: true
                    }
                }]
            }
        }
    };

    // Create new instance of chart
    var barChart = document.getElementById('canvas-barchart').getContext('2d');
    window.myBar = new Chart(barChart, barChartConfig);

    // Generate dynamic data on load
    generateDynamicChart();
});
